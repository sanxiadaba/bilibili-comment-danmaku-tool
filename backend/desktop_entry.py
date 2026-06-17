import argparse
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import server as server_module
from app_logging import configure_logging, logging_status, log_event, shutdown_logging
from bilibili_comment_danmaku import prepare_database_path
from bilibili_comment_danmaku.storage import connect, ensure_schema
from http_utils import safe_print
from server import (
    DEFAULT_COOKIE_FILE,
    DEFAULT_DB,
    DEFAULT_LOG_DIR,
    DEFAULT_SPACE_CACHE_DIR,
    DEFAULT_STATIC,
    CommentDanmakuServer,
    configure_task_services,
)


def app_root():
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        exe_dir = Path(sys.argv[0]).resolve().parent
        return exe_dir.parent if exe_dir.name == "_internal" else exe_dir
    return Path(__file__).resolve().parent.parent


def bundled_static_dir(root):
    candidates = [
        root / "dist",
        root / "_internal" / "dist",
        Path(__file__).resolve().parent / "dist",
        Path(__file__).resolve().parent.parent / "dist",
        DEFAULT_STATIC,
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate.resolve()
    return candidates[0].resolve()


def open_browser_later(url, delay=0.8):
    def worker():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as exc:
            log_event("desktop.browser_open_error", str(exc), level="warning")

    threading.Thread(target=worker, name="desktop-browser-open", daemon=True).start()


def initialize_database(db_path):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()


def main():
    root = app_root()
    parser = argparse.ArgumentParser(description="Run Bilibili comment/danmaku tool as a local desktop app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--db", default=str(root / "data" / DEFAULT_DB.name))
    parser.add_argument("--static", default=str(bundled_static_dir(root)))
    parser.add_argument("--log-dir", default=str(root / DEFAULT_LOG_DIR.name))
    parser.add_argument("--database-dir", default=str(root / "data" / "databases"))
    parser.add_argument("--space-cache-dir", default=str(root / "data" / "space_cache"))
    args = parser.parse_args()

    log_dir = Path(args.log_dir).resolve()
    configure_logging(log_dir)

    handler = type(
        "DesktopCommentDanmakuServer",
        (CommentDanmakuServer,),
        {
            "db_path": Path(args.db).resolve(),
            "static_dir": Path(args.static).resolve(),
            "log_dir": log_dir,
            "database_dir": Path(args.database_dir).resolve(),
        },
    )
    handler.db_path = prepare_database_path(handler.db_path)
    initialize_database(handler.db_path)
    handler.database_dir.mkdir(parents=True, exist_ok=True)

    cookie_file = root / "data" / DEFAULT_COOKIE_FILE.name
    configure_task_services(cookie_file, Path(args.space_cache_dir).resolve(), persist=True)
    server_module.space_archive_service.start_pending_tasks()
    server_module.video_parse_service.start_pending_tasks()
    server_module.archive_delete_service.start_pending_tasks()

    url = f"http://{args.host}:{args.port}/"
    server = ThreadingHTTPServer((args.host, args.port), handler)
    log_event(
        "desktop.start",
        "desktop app server started",
        host=args.host,
        port=args.port,
        db=str(handler.db_path),
        static_dir=str(handler.static_dir),
        log_dir=str(handler.log_dir),
        database_dir=str(handler.database_dir),
        logging=logging_status(),
    )
    safe_print(f"Bilibili comment/danmaku tool is running at {url}")
    if not args.no_browser:
        open_browser_later(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("desktop.stop", "desktop app stopped by keyboard interrupt")
    finally:
        server.server_close()
        shutdown_logging()


if __name__ == "__main__":
    main()
