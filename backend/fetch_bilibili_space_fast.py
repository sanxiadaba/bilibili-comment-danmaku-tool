import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bilibili_comment_danmaku import scraper
from bilibili_comment_danmaku.danmaku import scrape_danmaku
from bilibili_comment_danmaku.storage import (
    connect,
    ensure_schema,
    prepare_database_path,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"
DEFAULT_CACHE_DIR = ROOT / "data" / "space_cache"


def load_cookie(path):
    return scraper.load_cookie_file(path) if path and Path(path).exists() else ""


def event(name, **fields):
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "event": name, **fields}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def fetch_space_videos(mid, cookie, cache_path=None, use_cache=True, use_proxy=False):
    if use_cache and cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        items = cached.get("items") if isinstance(cached, dict) else None
        if isinstance(items, list):
            event("space.cache_hit", path=str(cache_path), total=len(items))
            return items

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://space.bilibili.com/{mid}/video",
        "Origin": "https://space.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    client = scraper.BilibiliClient(headers, use_proxy=use_proxy)
    mixin = scraper.get_wbi_mixin_key(client, lambda message: event("space.nav", message=message))
    endpoint = "https://api.bilibili.com/x/space/wbi/arc/search"
    items = []
    page = 1
    while True:
        params = scraper.sign_wbi_params(
            {
                "mid": mid,
                "pn": page,
                "ps": 30,
                "tid": 0,
                "order": "pubdate",
                "platform": "web",
                "web_location": 1550101,
            },
            mixin,
        )
        payload = client.request_json(scraper.build_url(endpoint, params), timeout=30)
        data = payload.get("data") or {}
        vlist = ((data.get("list") or {}).get("vlist") or [])
        total = (data.get("page") or {}).get("count") or 0
        event("space.page", page=page, got=len(vlist), total=total)
        items.extend(vlist)
        if not vlist or len(items) >= total:
            break
        page += 1
        time.sleep(random.uniform(2.0, 5.0))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "mid": str(mid),
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "total": len(items),
                    "items": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        event("space.cache_write", path=str(cache_path), total=len(items))
    return items


def db_status(db_path, mid):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        rows = conn.execute(
            """
            SELECT v.bvid, COUNT(DISTINCT c.rpid) AS comments, COUNT(DISTINCT d.dmid) AS danmaku
            FROM videos v
            LEFT JOIN comments c ON c.bvid = v.bvid
            LEFT JOIN danmaku d ON d.bvid = v.bvid
            WHERE v.owner_mid = ?
            GROUP BY v.bvid
            """,
            (str(mid),),
        ).fetchall()
        return {
            row["bvid"]: {
                "comments": row["comments"] or 0,
                "danmaku": row["danmaku"] or 0,
            }
            for row in rows
        }
    finally:
        conn.close()


def is_complete(item, status):
    bvid = item.get("bvid")
    saved = status.get(bvid or "")
    return bool(saved and saved["comments"] > 0 and saved["danmaku"] > 0)


def log_progress(bvid):
    def log(message):
        if (
            message.startswith("main page")
            or message.startswith("main page limit")
            or message.startswith("skipping children")
            or message.startswith("danmaku:")
            or message.startswith("login:")
            or message.startswith("warmup:")
            or message.startswith("warning:")
            or "slow request" in message
        ):
            event("video.progress", bvid=bvid, message=message)

    return log


def archive_one(item, args, cookie):
    bvid = item["bvid"]
    started = time.perf_counter()
    log = log_progress(bvid)
    event("video.start", bvid=bvid, title=item.get("title"), mode="fast")
    comments = scraper.scrape_comments(
        bvid,
        cookie=cookie,
        cookie_file=args.cookie_file,
        delay=args.delay,
        use_proxy=args.proxy,
        logger=log,
        max_main_pages=args.comment_pages,
        fetch_children=False,
    )
    save_comments_to_sqlite(comments, args.db, replace=False)
    headers = scraper.make_headers(bvid, cookie)
    danmaku = scrape_danmaku(
        bvid,
        comments.get("video_raw"),
        headers=headers,
        use_proxy=args.proxy,
        logger=log,
        fetch_likes=not args.skip_danmaku_likes,
    )
    if danmaku.get("items"):
        save_danmaku_to_sqlite(danmaku, args.db, replace=True)
    event(
        "video.done",
        bvid=bvid,
        title=item.get("title"),
        comments=comments["metadata"].get("comment_total_count"),
        api_comment_count=comments["metadata"].get("api_comment_count"),
        danmaku=len(danmaku.get("items") or []),
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fast sequential archive for all videos of a Bilibili UP owner."
    )
    parser.add_argument("mid", help="Bilibili UP owner mid")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--cookie", default=os.environ.get("BILIBILI_COOKIE", ""))
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--between-videos-min", type=float, default=8.0)
    parser.add_argument("--between-videos-max", type=float, default=20.0)
    parser.add_argument("--comment-pages", type=int, default=1)
    parser.add_argument("--skip-danmaku-likes", action="store_true", default=True)
    parser.add_argument("--with-danmaku-likes", dest="skip_danmaku_likes", action="store_false")
    parser.add_argument("--proxy", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.db = str(prepare_database_path(args.db))
    cookie = args.cookie or load_cookie(args.cookie_file)
    cache_path = DEFAULT_CACHE_DIR / f"space_{args.mid}_videos.json"
    items = fetch_space_videos(
        args.mid,
        cookie,
        cache_path=cache_path,
        use_cache=not args.no_cache,
        use_proxy=args.proxy,
    )
    if args.limit > 0:
        items = items[: args.limit]
    event(
        "batch.start",
        mid=args.mid,
        total=len(items),
        comment_pages=args.comment_pages,
        fetch_children=False,
        fetch_danmaku_likes=not args.skip_danmaku_likes,
    )

    index = 0
    while index < len(items):
        item = items[index]
        status = db_status(args.db, args.mid)
        complete = sum(1 for video in items if is_complete(video, status))
        if is_complete(item, status):
            event(
                "video.skip",
                index=index + 1,
                total=len(items),
                complete=complete,
                bvid=item.get("bvid"),
                reason="already_complete",
            )
            index += 1
            continue
        try:
            archive_one(item, args, cookie)
            index += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            event("video.error", index=index + 1, bvid=item.get("bvid"), error=str(exc))
            pause = random.uniform(600, 1800)
            event("video.pause_after_error", seconds=round(pause, 1))
            time.sleep(pause)
            continue
        if index < len(items):
            pause = random.uniform(args.between_videos_min, args.between_videos_max)
            event("video.pause", seconds=round(pause, 1), next_index=index + 1)
            time.sleep(pause)

    status = db_status(args.db, args.mid)
    complete = sum(1 for video in items if is_complete(video, status))
    event("batch.finish", mid=args.mid, total=len(items), complete=complete)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
