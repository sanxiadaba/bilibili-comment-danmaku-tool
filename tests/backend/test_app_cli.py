import unittest
import sys
import io
import json
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TEST_BACKEND = ROOT / "tests" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(TEST_BACKEND) not in sys.path:
    sys.path.insert(0, str(TEST_BACKEND))

from helpers import BVID, make_archive, make_comment  # noqa: E402
from app_cli import build_parser, main, print_result, run_fetch_video, run_list_space  # noqa: E402
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

    def test_fetch_space_videos_does_not_cache_partial_results(self):
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

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "space_1538787344_videos.json"
            with patch("space_archive.scraper.get_wbi_mixin_key", return_value="mixin"):
                with patch("space_archive.fetch_space_page", side_effect=fake_page):
                    items = fetch_space_videos("1538787344", "", cache_path=cache_path, use_cache=True, max_items=1)

            self.assertEqual(items, [{"bvid": "BV1"}])
            self.assertFalse(cache_path.exists())

    def test_list_space_returns_trimmed_video_payload(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "list-space",
                "https://space.bilibili.com/1538787344",
                "--max-videos",
                "1",
                "--no-cache",
            ]
        )
        with patch("app_cli.scraper.load_cookie_file", return_value="cookie"):
            with patch(
                "app_cli.fetch_space_videos",
                return_value=[
                    {"bvid": "BV1", "title": "one", "created": 1, "comment": 2, "video_review": 3},
                    {"bvid": "BV2", "title": "two", "created": 4, "comment": 5, "video_review": 6},
                ],
            ) as fetch_space:
                result = run_list_space(args)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mid"], "1538787344")
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["videos"], [{"bvid": "BV1", "title": "one", "created": 1, "comment": 2, "danmaku": 3}])
        self.assertEqual(fetch_space.call_args.kwargs["max_items"], 1)
        self.assertFalse(fetch_space.call_args.kwargs["use_cache"])

    def test_fetch_video_saves_comments_and_danmaku_to_owner_database(self):
        archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
        danmaku = {
            "bvid": BVID,
            "cid": "456",
            "fetched_at": "2024-01-01T00:00:00+00:00",
            "metadata": {"bvid": BVID, "cid": "456", "fetched_at": "2024-01-01T00:00:00+00:00"},
            "items": [
                {
                    "dmid": "1",
                    "bvid": BVID,
                    "cid": "456",
                    "progress": 1000,
                    "mode": 1,
                    "font_size": 25,
                    "color": 16777215,
                    "ctime": 1700000000,
                    "pool": 0,
                    "user_hash": "hash",
                    "weight": 0,
                    "like_count": 0,
                    "content": "danmaku",
                    "fetched_at": "2024-01-01T00:00:00+00:00",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            parser = build_parser()
            args = parser.parse_args(["fetch-video", BVID, "--database-dir", str(Path(tmp) / "databases")])
            with patch("app_cli.scrape_comments", return_value=archive) as scrape_comments:
                with patch("app_cli.scrape_danmaku", return_value=danmaku) as scrape_danmaku:
                    result = run_fetch_video(args)
            db_exists = Path(result["db"]).exists()

        self.assertTrue(result["ok"])
        self.assertEqual(result["bvid"], BVID)
        self.assertEqual(result["comments"], 1)
        self.assertEqual(result["danmaku"], 1)
        self.assertIn("Owner_42", result["db"])
        self.assertTrue(result["db"].endswith(f"{BVID}.db"))
        self.assertTrue(db_exists)
        scrape_comments.assert_called_once()
        scrape_danmaku.assert_called_once()

    def test_fetch_video_skip_danmaku_does_not_call_danmaku_api(self):
        archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
        with tempfile.TemporaryDirectory() as tmp:
            parser = build_parser()
            args = parser.parse_args(
                ["fetch-video", BVID, "--database-dir", str(Path(tmp) / "databases"), "--skip-danmaku"]
            )
            with patch("app_cli.scrape_comments", return_value=archive):
                with patch("app_cli.scrape_danmaku") as scrape_danmaku:
                    result = run_fetch_video(args)

        self.assertEqual(result["danmaku"], 0)
        scrape_danmaku.assert_not_called()

    def test_json_output_is_ascii_and_round_trips_unicode(self):
        payload = {
            "ok": True,
            "command": "list-space",
            "mid": "1538787344",
            "fetched": 1,
            "returned": 1,
            "videos": [{"bvid": "BV1", "title": "[编程语言杂谈]C语言设计缺陷", "created": 0, "comment": 0, "danmaku": 0}],
        }
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            print_result(payload, json_output=True)

        output = stdout.getvalue()
        output.encode("ascii")
        parsed = json.loads(output)
        self.assertEqual(parsed["videos"][0]["title"], "[编程语言杂谈]C语言设计缺陷")

    def test_main_returns_json_error_for_invalid_space_ref(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["--json", "list-space", "not-a-space-ref"])

        self.assertEqual(status, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], 500)
        self.assertIn("owner_ref", payload["error"])
        self.assertEqual(stderr.getvalue(), "")

    def test_build_script_uses_multisize_png_icon_and_launcher_icon(self):
        script = (ROOT / "scripts" / "build_nuitka_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("assets\\app-icon.png", script)
        self.assertIn('Join-Path $env:TEMP "bilibili-comment-danmaku-tool.ico"', script)
        self.assertIn("foreach ($size in @(256, 128, 64, 48, 32, 16))", script)
        self.assertIn("Format32bppArgb", script)
        self.assertIn("ImageFormat]::Png", script)
        self.assertIn("--windows-icon-from-ico=$iconPath", script)
        self.assertIn('/win32icon:"$iconPath"', script)
        self.assertIn("Icon.ExtractAssociatedIcon(Application.ExecutablePath)", script)

    def test_build_script_wraps_cli_and_gui_modes(self):
        script = (ROOT / "scripts" / "build_nuitka_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("IsCliMode(args[0])", script)
        self.assertIn('return mode == "cli" || mode == "serve" || mode == "server"', script)
        self.assertIn('return new[] { "--cli" }.Concat(args.Skip(1)).ToArray();', script)
        self.assertIn("RunConsole(target, root, forwarded)", script)
        self.assertIn("RedirectStandardOutput = true", script)
        self.assertIn("RedirectStandardError = true", script)
        self.assertIn("FreeConsole();", script)
        self.assertIn("CreateNoWindow = true", script)

    def test_desktop_entry_dispatches_cli_before_starting_gui_server(self):
        source = (ROOT / "backend" / "desktop_entry.py").read_text(encoding="utf-8")

        self.assertIn('if "--cli" in sys.argv:', source)
        self.assertIn("from app_cli import main as cli_main", source)
        self.assertLess(source.index('if "--cli" in sys.argv:'), source.index("parser = argparse.ArgumentParser"))


if __name__ == "__main__":
    unittest.main()
