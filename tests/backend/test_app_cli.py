import unittest
import sys
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app_cli import build_parser  # noqa: E402
from space_archive import fetch_space_videos, normalize_space_archive_options  # noqa: E402


class AppCliTests(unittest.TestCase):
    def test_fetch_alias_parses_as_fetch_video(self):
        parser = build_parser()
        args = parser.parse_args(["fetch", "BV1xx411c7mD", "--skip-danmaku"])

        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.video, "BV1xx411c7mD")
        self.assertTrue(args.skip_danmaku)

    def test_archive_space_accepts_max_videos(self):
        parser = build_parser()
        args = parser.parse_args(["archive-space", "https://space.bilibili.com/1538787344", "--max-videos", "1"])

        self.assertEqual(args.owner_ref, "https://space.bilibili.com/1538787344")
        self.assertEqual(args.max_videos, 1)

    def test_space_archive_options_include_max_videos(self):
        options = normalize_space_archive_options({"max_videos": 2})

        self.assertEqual(options["max_videos"], 2)

    def test_fetch_space_videos_stops_after_max_items(self):
        def fake_page(client, endpoint, params, page, mid, mixin_key, log):
            return (
                {
                    "data": {
                        "page": {"count": 46},
                        "list": {"vlist": [{"bvid": "BV1"}, {"bvid": "BV2"}]},
                    }
                },
                mixin_key,
            )

        with patch("space_archive.scraper.get_wbi_mixin_key", return_value="mixin"):
            with patch("space_archive.fetch_space_page", side_effect=fake_page) as fetch_page:
                items = fetch_space_videos("1538787344", "", use_cache=False, max_items=1)

        self.assertEqual(items, [{"bvid": "BV1"}])
        self.assertEqual(fetch_page.call_count, 1)


if __name__ == "__main__":
    unittest.main()
