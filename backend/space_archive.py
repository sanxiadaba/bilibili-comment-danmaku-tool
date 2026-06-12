import json
import random
import re
import time
from datetime import datetime, timezone

from app_logging import log_event, log_exception
from bilibili_comment_danmaku import save_comments_to_sqlite, save_danmaku_to_sqlite, scrape_comments, scrape_danmaku
from bilibili_comment_danmaku import scraper
from bilibili_comment_danmaku.scraper import BilibiliRequestError
from bilibili_comment_danmaku.storage import connect, ensure_schema
from progress_state import clamp_float, first_int, parse_float, start_progress, update_progress, finish_progress, fail_progress
from task_queue import InMemoryTaskQueue


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fetch_space_videos(mid, cookie, cache_path=None, use_cache=True):
    if use_cache and cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        items = cached.get("items") if isinstance(cached, dict) else None
        if isinstance(items, list):
            log_event("task.space_archive.cache_hit", "loaded cached UP video list", mid=mid, total=len(items))
            return items

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://space.bilibili.com/{mid}/video",
        "Origin": "https://space.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    client = scraper.BilibiliClient(headers, use_proxy=False)
    mixin = scraper.get_wbi_mixin_key(client, lambda message: update_progress("space", mid, message))
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
        update_progress("space", mid, f"UP视频列表页 page={page} got={len(vlist)} total={total}")
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
                    "cached_at": utc_now(),
                    "total": len(items),
                    "items": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return items


def db_status(db_path, mid):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        rows = conn.execute(
            """
            SELECT
                v.bvid,
                v.fetched_at,
                v.video_cid,
                v.api_comment_count,
                v.stat_reply,
                v.stat_danmaku,
                COALESCE(c.comments, 0) AS comments,
                COALESCE(d.danmaku, 0) AS danmaku
            FROM videos v
            LEFT JOIN (
                SELECT bvid, COUNT(*) AS comments
                FROM comments
                GROUP BY bvid
            ) c ON c.bvid = v.bvid
            LEFT JOIN (
                SELECT bvid, COUNT(*) AS danmaku
                FROM danmaku
                GROUP BY bvid
            ) d ON d.bvid = v.bvid
            WHERE v.owner_mid = ?
            """,
            (str(mid),),
        ).fetchall()
        return {
            row["bvid"]: {
                "fetched_at": row["fetched_at"],
                "video_cid": row["video_cid"],
                "api_comment_count": row["api_comment_count"],
                "stat_reply": row["stat_reply"],
                "stat_danmaku": row["stat_danmaku"],
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
    if not saved or not saved.get("fetched_at"):
        return False

    expected_comments = first_int(item.get("comment"), saved.get("stat_reply"), saved.get("api_comment_count"))
    expected_danmaku = first_int(item.get("video_review"), saved.get("stat_danmaku"))

    comments_complete = expected_comments == 0 or saved["comments"] > 0 or saved.get("api_comment_count") == 0
    danmaku_complete = expected_danmaku == 0 or saved["danmaku"] > 0
    return bool(comments_complete and danmaku_complete)


def normalize_space_archive_options(body):
    options = {
        "delay": clamp_float(parse_float(body.get("delay"), 1.0), 0.0, 5.0),
        "between_videos_min": clamp_float(parse_float(body.get("between_videos_min"), 8.0), 0.0, 3600.0),
        "between_videos_max": clamp_float(parse_float(body.get("between_videos_max"), 20.0), 0.0, 3600.0),
        "no_cache": bool(body.get("no_cache")),
    }
    if options["between_videos_max"] < options["between_videos_min"]:
        options["between_videos_max"] = options["between_videos_min"]
    return options


class SpaceArchiveService:
    def __init__(self, cookie_file, cache_dir, refresh_lock):
        self.cookie_file = cookie_file
        self.cache_dir = cache_dir
        self.refresh_lock = refresh_lock
        self.queue = InMemoryTaskQueue("space", self.run_queue_task)

    def enqueue(self, db_path, mid, owner_ref, options, request_id=""):
        return self.queue.enqueue(
            {
                "mid": str(mid),
                "owner_ref": owner_ref,
                "request_id": request_id,
                "db_path": str(db_path),
                "options": dict(options),
            }
        )

    def snapshot(self):
        return self.queue.snapshot()

    def update_task(self, task, **fields):
        self.queue.update(task, **fields)

    def run_queue_task(self, task):
        self.refresh_lock.acquire()
        try:
            self.queue.update(
                task,
                status="running",
                started_at=utc_now(),
                message="正在抓取",
            )
            start_progress("space", task["mid"], f"准备抓取 UP {task['mid']} 的视频列表")
            self.run_archive_task(task)
        finally:
            self.refresh_lock.release()

    def run_archive_task(self, task):
        db_path = task["db_path"]
        mid = task["mid"]
        options = task["options"]
        request_id = task.get("request_id", "")
        cache_path = self.cache_dir / f"space_{mid}_videos.json"
        cookie = scraper.load_cookie_file(self.cookie_file) if self.cookie_file.exists() else ""
        total = 0
        complete = 0
        archived = 0
        skipped = 0
        failed = 0
        current_bvid = ""
        try:
            log_event(
                "task.space_archive.start",
                "space archive task started",
                request_id=request_id,
                mid=mid,
                task_id=task["id"],
                **options,
            )
            update_progress("space", mid, f"正在读取 UP {mid} 的视频列表")
            self.update_task(task, message="正在读取视频列表", progress=5)
            items = fetch_space_videos(
                mid,
                cookie,
                cache_path=cache_path,
                use_cache=not options.get("no_cache"),
            )
            total = len(items)
            self.update_task(task, total=total, message=f"视频列表完成，共 {total} 个视频")
            update_progress("space", mid, f"UP视频列表完成 total={total} complete=0 archived=0 skipped=0 failed=0")
            status = db_status(db_path, mid)
            complete = sum(1 for video in items if is_complete(video, status))
            for index, item in enumerate(items, start=1):
                current_bvid = item.get("bvid") or ""
                if is_complete(item, status):
                    skipped += 1
                    self.update_task(
                        task,
                        current_bvid=current_bvid,
                        total=total,
                        complete=complete,
                        archived=archived,
                        skipped=skipped,
                        failed=failed,
                        progress=space_task_percent(index, total),
                        message=f"跳过已完成视频 {index}/{total}",
                    )
                    update_progress(
                        "space",
                        current_bvid or mid,
                        f"UP视频跳过 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
                    )
                    continue

                self.update_task(
                    task,
                    current_bvid=current_bvid,
                    total=total,
                    complete=complete,
                    archived=archived,
                    skipped=skipped,
                    failed=failed,
                    progress=space_task_percent(index, total),
                    message=f"正在抓取视频 {index}/{total}",
                )
                update_progress(
                    "space",
                    current_bvid or mid,
                    f"UP视频抓取 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
                )
                try:
                    comments = scrape_comments(
                        current_bvid,
                        cookie=cookie,
                        cookie_file=str(self.cookie_file),
                        delay=options.get("delay", 1.0),
                        logger=lambda message, bvid=current_bvid: log_space_video_progress(bvid, message),
                        max_main_pages=None,
                        fetch_children=True,
                    )
                    self.update_task(task, message=f"正在保存评论 {index}/{total}")
                    update_progress("space", current_bvid, f"UP视频保存评论 {index}/{total} bvid={current_bvid}")
                    save_comments_to_sqlite(comments, db_path, replace=False)

                    headers = scraper.make_headers(current_bvid, cookie)
                    danmaku_result = scrape_danmaku(
                        current_bvid,
                        comments.get("video_raw"),
                        headers=headers,
                        logger=lambda message, bvid=current_bvid: log_space_video_progress(bvid, message),
                        fetch_likes=True,
                    )
                    if danmaku_result.get("items"):
                        self.update_task(task, message=f"正在保存弹幕 {index}/{total}")
                        update_progress("space", current_bvid, f"UP视频保存弹幕 {index}/{total} bvid={current_bvid}")
                        save_danmaku_to_sqlite(danmaku_result, db_path, replace=True)
                    else:
                        update_progress("space", current_bvid, f"UP视频弹幕为空已跳过保存 {index}/{total} bvid={current_bvid}")

                    archived += 1
                    status[current_bvid] = {
                        "api_comment_count": comments.get("metadata", {}).get("api_comment_count"),
                        "comments": len(comments.get("comment_items") or []),
                        "danmaku": len(danmaku_result.get("items") or []),
                    }
                    complete += 1
                    self.update_task(
                        task,
                        complete=complete,
                        archived=archived,
                        skipped=skipped,
                        failed=failed,
                        progress=space_task_percent(index, total),
                        message=f"视频完成 {index}/{total}",
                    )
                    log_event(
                        "task.space_archive.video_finish",
                        "space archive video finished",
                        request_id=request_id,
                        mid=mid,
                        task_id=task["id"],
                        bvid=current_bvid,
                        index=index,
                        total=total,
                        archived=archived,
                        complete=complete,
                        failed=failed,
                    )
                except Exception as exc:
                    if should_abort_space_archive(exc):
                        raise
                    failed += 1
                    payload, status_code = api_error_response(exc)
                    self.update_task(
                        task,
                        failed=failed,
                        current_bvid=current_bvid,
                        progress=space_task_percent(index, total),
                        message=f"视频失败，已跳过 {index}/{total}",
                    )
                    update_progress(
                        "space",
                        current_bvid or mid,
                        f"UP视频失败 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
                    )
                    log_exception(
                        "task.space_archive.video_error",
                        payload["error"],
                        request_id=request_id,
                        mid=mid,
                        task_id=task["id"],
                        bvid=current_bvid,
                        index=index,
                        total=total,
                        complete=complete,
                        archived=archived,
                        skipped=skipped,
                        failed=failed,
                        status=status_code,
                    )
                if index < total:
                    pause = random.uniform(options.get("between_videos_min", 8.0), options.get("between_videos_max", 20.0))
                    self.update_task(task, message=f"等待下一条 {index}/{total}")
                    update_progress("space", current_bvid, f"UP视频间隔 {index}/{total} seconds={pause:.1f} next={index + 1}")
                    time.sleep(pause)

            status = db_status(db_path, mid)
            complete = sum(1 for video in items if is_complete(video, status))
            self.update_task(
                task,
                status="finished",
                message=f"已完成 {complete}/{total}",
                finished_at=utc_now(),
                total=total,
                complete=complete,
                archived=archived,
                skipped=skipped,
                failed=failed,
                progress=100,
            )
            finish_progress("space", mid, f"UP 主归档完成：{complete}/{total} 个视频已有评论和弹幕，失败 {failed} 个")
            log_event(
                "task.space_archive.finish",
                "space archive task finished",
                request_id=request_id,
                mid=mid,
                task_id=task["id"],
                total=total,
                complete=complete,
                archived=archived,
                skipped=skipped,
                failed=failed,
            )
        except Exception as exc:
            payload, status_code = api_error_response(exc)
            self.update_task(
                task,
                status="failed",
                message=payload["error"],
                finished_at=utc_now(),
                current_bvid=current_bvid,
                total=total,
                complete=complete,
                archived=archived,
                skipped=skipped,
                failed=failed,
            )
            fail_progress("space", current_bvid or mid, payload["error"])
            log_exception(
                "task.space_archive.error",
                payload["error"],
                request_id=request_id,
                mid=mid,
                task_id=task["id"],
                bvid=current_bvid,
                total=total,
                complete=complete,
                archived=archived,
                skipped=skipped,
                failed=failed,
                status=status_code,
            )


def space_task_percent(index, total):
    if not total:
        return 0
    return min(99, max(1, int((index / total) * 100)))


def log_space_video_progress(bvid, message):
    if (
        message.startswith("main page")
        or message.startswith("main page limit")
        or message.startswith("skipping children")
        or message.startswith("danmaku:")
        or message.startswith("parsed xml")
        or message.startswith("fetching xml")
        or message.startswith("warmup:")
        or message.startswith("wbi:")
        or message.startswith("video info:")
        or message.startswith("video:")
        or message.startswith("main replies:")
        or message.startswith("warning:")
        or message.startswith("comments closed:")
        or "slow request" in message
    ):
        update_progress("space", bvid, message)


def api_error_response(exc):
    message = str(exc)
    lower_message = message.lower()

    if isinstance(exc, scraper.WbiSignatureUnavailableError):
        return (
            {
                "error": "WBI 签名接口暂不可用，已暂停本轮 UP 归档。稍后重新抓取同一个 UP 时，已归档视频会自动跳过。",
                "detail": message,
            },
            502,
        )

    if (isinstance(exc, BilibiliRequestError) and exc.status == 412) or "http error 412" in lower_message:
        return (
            {
                "error": "Bilibili 接口返回 412，通常表示当前 Cookie、会话指纹或请求上下文未通过接口预检。工具已重新签名、冷却退避并重试；如果仍失败，请暂停一段时间后再试，必要时更新 Cookie。",
                "detail": message,
            },
            502,
        )

    if (
        (isinstance(exc, BilibiliRequestError) and exc.api_code == -352)
        or "api code=-352" in lower_message
        or "api code -352" in lower_message
    ):
        return (
            {
                "error": "Bilibili 接口返回风控校验失败，通常与请求频率、Cookie 状态或访问环境有关。工具已自动进入长冷却退避；请暂停一段时间后再试。",
                "detail": message,
            },
            502,
        )

    if (isinstance(exc, BilibiliRequestError) and exc.status == 429) or "http error 429" in lower_message:
        return (
            {
                "error": "Bilibili 接口返回 429，说明当前访问频率已被明确限制。工具已自动进入长冷却退避；请避免连续手动刷新。",
                "detail": message,
            },
            502,
        )

    if "consecutive_very_slow_requests" in lower_message or "slow_limit_cooldown" in lower_message:
        return (
            {
                "error": "Bilibili 接口响应持续异常变慢，通常是软限流或账号/IP 级降速。工具已进入更长冷却，避免继续把风控时间拉长。",
                "detail": message,
            },
            502,
        )

    if "http error" in lower_message or "request failed after" in lower_message:
        return (
            {
                "error": "Bilibili 接口请求失败，可能是网络、登录态、风控或接口临时不可用。",
                "detail": message,
            },
            502,
        )

    if "[errno 22] invalid argument" in lower_message:
        return (
            {
                "error": "本地服务输出流异常，已避免让日志写入中断抓取。请重启服务后重试。",
                "detail": message,
            },
            500,
        )

    return ({"error": message}, 500)


def should_abort_space_archive(exc):
    lower_message = str(exc).lower()
    return (
        isinstance(exc, scraper.WbiSignatureUnavailableError)
        or scraper.is_blocked_request_error(exc)
        or (isinstance(exc, BilibiliRequestError) and exc.status in {412, 429})
        or "http error 412" in lower_message
        or "http error 429" in lower_message
        or "api code=-352" in lower_message
        or "api code -352" in lower_message
        or "consecutive_very_slow_requests" in lower_message
        or "slow_limit_cooldown" in lower_message
    )


def extract_space_mid(value):
    value = (value or "").strip()
    if not value:
        return ""
    url_match = re.search(r"space\.bilibili\.com/(\d+)", value)
    if url_match:
        return url_match.group(1)
    mid_match = re.search(r"^\d{2,}$", value)
    if mid_match:
        return mid_match.group(0)
    return ""
