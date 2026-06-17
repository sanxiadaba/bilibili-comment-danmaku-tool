import argparse
import os
from pathlib import Path
import sys

from bilibili_comment_danmaku import DEFAULT_BVID, prepare_database_path, save_comments_to_sqlite, scrape_comments
from database_registry import video_database_path_from_archive


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_DATABASE_DIR = ROOT / "data" / "databases"
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"


def main():
    parser = argparse.ArgumentParser(description="Fetch Bilibili video comments and danmaku into SQLite.")
    parser.add_argument("video", nargs="?", default=DEFAULT_BVID, help="Bilibili video URL or BV id")
    parser.add_argument("--bvid", help="Backward-compatible alias for a BV id")
    parser.add_argument("--db")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--cookie", default=os.environ.get("BILIBILI_COOKIE", ""))
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--proxy", action="store_true", help="Use the scraper HTTP proxy for Bilibili requests.")
    parser.add_argument("--comment-pages", type=int, default=0, help="Only fetch the first N main comment pages.")
    parser.add_argument("--skip-children", action="store_true", help="Skip nested reply API requests.")
    args = parser.parse_args()

    video_ref = args.bvid or args.video
    archive = scrape_comments(
        video_ref,
        cookie=args.cookie,
        cookie_file=args.cookie_file,
        delay=args.delay,
        use_proxy=args.proxy,
        max_main_pages=args.comment_pages if args.comment_pages > 0 else None,
        fetch_children=not args.skip_children,
    )
    args.db = str(prepare_database_path(args.db or video_database_path_from_archive(archive, DEFAULT_DATABASE_DIR)))
    summary = save_comments_to_sqlite(archive, args.db)
    print(f"saved sqlite database: {summary['db']}", flush=True)
    print(f"bvid: {summary['bvid']}", flush=True)
    print(f"top_level_comment_count: {summary['top_level_comment_count']}", flush=True)
    print(f"nested_comment_count: {summary['nested_comment_count']}", flush=True)
    print(f"comment_total_count: {summary['total_count']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
