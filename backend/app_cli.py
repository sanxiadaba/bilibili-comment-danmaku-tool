import argparse
import json
import os
import sys
import threading
from pathlib import Path

from app_logging import configure_logging, shutdown_logging
from bilibili_comment_danmaku import (
    DEFAULT_BVID,
    prepare_database_path,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
    scrape_comments,
    scrape_danmaku,
)
from bilibili_comment_danmaku import scraper
from database_registry import DEFAULT_DATABASE_DIR, video_database_path_from_archive
from space_archive import (
    SpaceArchiveService,
    api_error_response,
    extract_space_mid,
    fetch_space_videos,
    normalize_space_archive_options,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_SPACE_CACHE_DIR = ROOT / "data" / "space_cache"


def app_root():
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        exe_dir = Path(sys.argv[0]).resolve().parent
        return exe_dir.parent if exe_dir.name == "_internal" else exe_dir
    return ROOT


def default_data_paths(root):
    return {
        "database_dir": root / "data" / "databases",
        "cookie_file": root / "data" / "cookie.txt",
        "space_cache_dir": root / "data" / "space_cache",
        "log_dir": root / "logs",
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Bilibili comment/danmaku command line tools.")
    parser.add_argument("--json", action="store_true", help="Print a JSON result.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    video = subparsers.add_parser("fetch-video", aliases=["fetch"], help="Fetch one video's comments and danmaku.")
    video.add_argument("video", nargs="?", default=DEFAULT_BVID, help="Bilibili video URL or BV id.")
    video.add_argument("--bvid", help="Backward-compatible alias for a BV id.")
    video.add_argument("--db", help="Explicit output SQLite path. Defaults to data/databases/<UP>/<BV>.db.")
    add_fetch_options(video)
    video.set_defaults(func=run_fetch_video)

    list_space = subparsers.add_parser("list-space", help="Fetch and print one UP owner's video list.")
    list_space.add_argument("owner_ref", help="Bilibili space URL or owner mid.")
    list_space.add_argument("--max-videos", type=int, default=0, help="Only print the first N videos.")
    list_space.add_argument("--no-cache", action="store_true", help="Ignore cached UP video list.")
    add_common_paths(list_space)
    list_space.set_defaults(func=run_list_space)

    archive = subparsers.add_parser("archive-space", help="Archive videos from one UP owner.")
    archive.add_argument("owner_ref", help="Bilibili space URL or owner mid.")
    archive.add_argument("--max-videos", type=int, default=0, help="Only archive the first N videos.")
    archive.add_argument("--between-videos-min", type=float, default=8.0)
    archive.add_argument("--between-videos-max", type=float, default=20.0)
    archive.add_argument("--no-cache", action="store_true", help="Ignore cached UP video list.")
    add_fetch_options(archive)
    archive.set_defaults(func=run_archive_space)

    return parser


def add_common_paths(parser):
    root = app_root()
    paths = default_data_paths(root)
    parser.add_argument("--database-dir", default=str(paths["database_dir"]))
    parser.add_argument("--cookie-file", default=str(paths["cookie_file"]))
    parser.add_argument("--space-cache-dir", default=str(paths["space_cache_dir"]))
    parser.add_argument("--log-dir", default=str(paths["log_dir"]))


def add_fetch_options(parser):
    add_common_paths(parser)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--cookie", default=os.environ.get("BILIBILI_COOKIE", ""))
    parser.add_argument("--proxy", action="store_true", help="Use the scraper HTTP proxy for Bilibili requests.")
    parser.add_argument("--comment-pages", type=int, default=0, help="Only fetch the first N main comment pages.")
    parser.add_argument("--skip-children", action="store_true", help="Skip nested reply API requests.")
    parser.add_argument("--skip-danmaku", action="store_true", help="Only fetch comments.")
    parser.add_argument("--skip-danmaku-likes", action="store_true", help="Skip danmaku like count requests.")


def run_fetch_video(args):
    video_ref = args.bvid or args.video
    archive = scrape_comments(
        video_ref,
        cookie=args.cookie,
        cookie_file=args.cookie_file,
        delay=args.delay,
        use_proxy=args.proxy,
        max_main_pages=args.comment_pages if args.comment_pages > 0 else None,
        fetch_children=not args.skip_children,
        logger=print_progress,
    )
    db_path = Path(args.db) if args.db else video_database_path_from_archive(archive, args.database_dir)
    db_path = prepare_database_path(db_path)
    comment_summary = save_comments_to_sqlite(archive, db_path, replace=True)

    danmaku_summary = None
    if not args.skip_danmaku:
        bvid = comment_summary["bvid"]
        cookie = args.cookie or scraper.load_cookie_file(args.cookie_file)
        headers = scraper.make_headers(bvid, cookie)
        danmaku = scrape_danmaku(
            bvid,
            archive.get("video_raw"),
            headers=headers,
            use_proxy=args.proxy,
            logger=print_progress,
            fetch_likes=not args.skip_danmaku_likes,
        )
        danmaku_summary = save_danmaku_to_sqlite(danmaku, db_path, replace=True)

    return {
        "ok": True,
        "command": "fetch-video",
        "db": str(db_path),
        "bvid": comment_summary["bvid"],
        "comments": comment_summary["total_count"],
        "top_level_comments": comment_summary["top_level_comment_count"],
        "nested_comments": comment_summary["nested_comment_count"],
        "danmaku": (danmaku_summary or {}).get("danmaku_count", 0),
    }


def run_list_space(args):
    mid = extract_space_mid(args.owner_ref)
    if not mid:
        raise ValueError("owner_ref must be a Bilibili space URL or numeric mid")
    cookie = scraper.load_cookie_file(args.cookie_file) if Path(args.cookie_file).exists() else ""
    cache_path = Path(args.space_cache_dir) / f"space_{mid}_videos.json"
    items = fetch_space_videos(
        mid,
        cookie,
        cache_path=cache_path,
        use_cache=not args.no_cache,
        max_items=args.max_videos,
    )
    max_videos = max(0, int(args.max_videos or 0))
    selected = items[:max_videos] if max_videos else items
    return {
        "ok": True,
        "command": "list-space",
        "mid": mid,
        "fetched": len(items),
        "returned": len(selected),
        "videos": [
            {
                "bvid": item.get("bvid", ""),
                "title": item.get("title", ""),
                "created": item.get("created", 0),
                "comment": item.get("comment", 0),
                "danmaku": item.get("video_review", 0),
            }
            for item in selected
        ],
    }


def run_archive_space(args):
    mid = extract_space_mid(args.owner_ref)
    if not mid:
        raise ValueError("owner_ref must be a Bilibili space URL or numeric mid")

    log_dir = Path(args.log_dir).resolve()
    configure_logging(log_dir, console=False)
    task = None
    try:
        options = normalize_space_archive_options(
            {
                "delay": args.delay,
                "between_videos_min": args.between_videos_min,
                "between_videos_max": args.between_videos_max,
                "max_videos": args.max_videos,
                "no_cache": args.no_cache,
            }
        )
        service = SpaceArchiveService(
            Path(args.cookie_file).resolve(),
            Path(args.space_cache_dir).resolve(),
            threading.Lock(),
            state_path=None,
        )
        task = service.queue.make_queued_task_locked(
            {
                "mid": mid,
                "owner_ref": args.owner_ref,
                "request_id": "cli",
                "database_dir": str(Path(args.database_dir).resolve()),
                "options": options,
            }
        )
        service.run_queue_task(task)
        result = service.queue.public_task(task)
        result.update({"ok": task.get("status") == "finished", "command": "archive-space", "log_dir": str(log_dir)})
        return result
    finally:
        shutdown_logging()


def print_progress(message):
    if message:
        print(message, flush=True)


def print_result(result, json_output=False):
    if json_output:
        print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
        return
    command = result.get("command", "")
    if command == "fetch-video":
        print(f"Saved: {result['db']}", flush=True)
        print(f"BV: {result['bvid']}", flush=True)
        print(f"Comments: {result['comments']}", flush=True)
        print(f"Danmaku: {result['danmaku']}", flush=True)
    elif command == "list-space":
        print(f"UP mid: {result['mid']}", flush=True)
        print(f"Videos: {result['returned']}/{result['fetched']}", flush=True)
        for item in result["videos"]:
            print(f"{item['bvid']}\t{item['title']}", flush=True)
    elif command == "archive-space":
        print(
            f"Archive: status={result.get('status')} total={result.get('total')} "
            f"archived={result.get('archived')} skipped={result.get('skipped')} failed={result.get('failed')}",
            flush=True,
        )
        print(f"Logs: {result.get('log_dir', '')}", flush=True)
    else:
        print(result, flush=True)


def main(argv=None):
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        payload, status = api_error_response(exc)
        if args.json:
            print(json.dumps({"ok": False, "status": status, **payload}, ensure_ascii=True, indent=2), flush=True)
        else:
            print(payload["error"], file=sys.stderr, flush=True)
            detail = payload.get("detail")
            if detail and detail != payload["error"]:
                print(detail, file=sys.stderr, flush=True)
        return 1
    print_result(result, args.json)
    return 0 if result.get("ok", True) else 1


def configure_stdio_utf8():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
