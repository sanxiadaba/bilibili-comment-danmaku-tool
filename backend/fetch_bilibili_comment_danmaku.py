import argparse
import os
from pathlib import Path
import sys

from bilibili_comment_danmaku import DEFAULT_BVID, scrape_to_sqlite


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comments.db"
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"


def main():
    parser = argparse.ArgumentParser(description="Fetch Bilibili video comments and danmaku into SQLite.")
    parser.add_argument("video", nargs="?", default=DEFAULT_BVID, help="Bilibili video URL or BV id")
    parser.add_argument("--bvid", help="Backward-compatible alias for a BV id")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--cookie", default=os.environ.get("BILIBILI_COOKIE", ""))
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--proxy", action="store_true", help="Use the scraper HTTP proxy for Bilibili requests.")
    args = parser.parse_args()

    video_ref = args.bvid or args.video
    Path(args.db).resolve().parent.mkdir(parents=True, exist_ok=True)
    summary = scrape_to_sqlite(
        video_ref,
        db_path=args.db,
        cookie=args.cookie,
        cookie_file=args.cookie_file,
        delay=args.delay,
        use_proxy=args.proxy,
    )
    print(f"saved sqlite database: {summary['db']}", flush=True)
    print(f"bvid: {summary['bvid']}", flush=True)
    print(f"top_level_count: {summary['top_level_count']}", flush=True)
    print(f"nested_reply_count: {summary['nested_reply_count']}", flush=True)
    print(f"flat_total_count: {summary['total_count']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
