import argparse
import os
import sys

from bilibili_comments import DEFAULT_BVID, scrape_to_sqlite


def main():
    parser = argparse.ArgumentParser(description="Fetch all Bilibili video comments into SQLite.")
    parser.add_argument("video", nargs="?", default=DEFAULT_BVID, help="Bilibili video URL or BV id")
    parser.add_argument("--bvid", help="Backward-compatible alias for a BV id")
    parser.add_argument("--db", default="comments.db")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--cookie", default=os.environ.get("BILIBILI_COOKIE", ""))
    parser.add_argument("--cookie-file", default="cookie.txt")
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    video_ref = args.bvid or args.video
    summary = scrape_to_sqlite(
        video_ref,
        db_path=args.db,
        cookie=args.cookie,
        cookie_file=args.cookie_file,
        delay=args.delay,
        use_proxy=not args.no_proxy,
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
