import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app_cli
import desktop_entry
from local_server import DEFAULT_PORT, create_threading_server, is_address_in_use


class DesktopPackagingReleaseTests(unittest.TestCase):
    def test_default_port_is_8001_and_server_walks_to_next_port(self):
        attempts = []

        class FakeServer:
            def __init__(self, address, handler):
                attempts.append(address)
                if address[1] in {8001, 8002}:
                    exc = OSError("in use")
                    exc.errno = 10048
                    raise exc
                self.address = address

        with patch("local_server.ThreadingHTTPServer", FakeServer):
            server, port = create_threading_server("127.0.0.1", DEFAULT_PORT, object, max_attempts=5)

        self.assertEqual(DEFAULT_PORT, 8001)
        self.assertEqual(port, 8003)
        self.assertEqual(server.address, ("127.0.0.1", 8003))
        self.assertEqual([item[1] for item in attempts], [8001, 8002, 8003])

    def test_port_probe_raises_after_configured_attempts(self):
        class AlwaysBusyServer:
            def __init__(self, address, handler):
                exc = OSError("in use")
                exc.errno = 10048
                raise exc

        with patch("local_server.ThreadingHTTPServer", AlwaysBusyServer):
            with self.assertRaisesRegex(OSError, "No free port found from 9000 to 9002"):
                create_threading_server("127.0.0.1", 9000, object, max_attempts=3)

    def test_address_in_use_includes_windows_access_denied_and_unix_busy(self):
        for code in (10048, 10013):
            exc = OSError()
            exc.errno = code
            self.assertTrue(is_address_in_use(exc))

    def test_desktop_default_paths_live_next_to_app_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_space_service = MagicMock()
            fake_video_service = MagicMock()
            fake_delete_service = MagicMock()
            with patch("desktop_entry.app_root", return_value=root), patch("desktop_entry.configure_logging"), patch(
                "desktop_entry.prepare_database_path", side_effect=lambda path: Path(path)
            ), patch("desktop_entry.initialize_database"), patch("desktop_entry.configure_task_services"), patch(
                "desktop_entry.create_threading_server"
            ) as create_server, patch("desktop_entry.open_browser_later"), patch.object(
                desktop_entry.server_module, "space_archive_service", fake_space_service
            ), patch.object(
                desktop_entry.server_module, "video_parse_service", fake_video_service
            ), patch.object(
                desktop_entry.server_module, "archive_delete_service", fake_delete_service
            ), patch("desktop_entry.shutdown_logging"):
                server = MagicMock()
                create_server.return_value = (server, 8001)
                with patch("sys.argv", ["bilibili-comment-danmaku-tool.exe", "--no-browser"]):
                    with redirect_stdout(io.StringIO()):
                        desktop_entry.main()

            handler = create_server.call_args.args[2]
            self.assertEqual(handler.db_path, (root / "data" / "comment_danmaku.db").resolve())
            self.assertEqual(handler.database_dir, (root / "data" / "databases").resolve())
            self.assertEqual(handler.log_dir, (root / "logs").resolve())
            fake_space_service.start_pending_tasks.assert_called_once()
            fake_video_service.start_pending_tasks.assert_called_once()
            fake_delete_service.start_pending_tasks.assert_called_once()
            server.serve_forever.assert_called_once()
            server.server_close.assert_called_once()

    def test_desktop_entry_forwards_cli_without_initializing_server(self):
        with patch("app_cli.main", return_value=7) as cli_main, patch("desktop_entry.create_threading_server") as create_server:
            with patch("sys.argv", ["bilibili-comment-danmaku-tool.exe", "--cli", "--json", "list-space", "1538787344"]):
                with self.assertRaises(SystemExit) as raised:
                    desktop_entry.main()

        self.assertEqual(raised.exception.code, 7)
        cli_main.assert_called_once_with(["--json", "list-space", "1538787344"])
        create_server.assert_not_called()

    def test_cli_default_paths_point_to_packaged_data_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app_cli.app_root", return_value=root):
                parser = app_cli.build_parser()
                fetch_args = parser.parse_args(["fetch-video", "BV1xx411c7mD"])
                list_args = parser.parse_args(["list-space", "1538787344"])

        self.assertEqual(Path(fetch_args.database_dir), root / "data" / "databases")
        self.assertEqual(Path(fetch_args.cookie_file), root / "data" / "cookie.txt")
        self.assertEqual(Path(fetch_args.space_cache_dir), root / "data" / "space_cache")
        self.assertEqual(Path(fetch_args.log_dir), root / "logs")
        self.assertEqual(Path(list_args.database_dir), root / "data" / "databases")

    def test_build_script_keeps_release_root_clean_with_single_visible_exe(self):
        script = (ROOT / "scripts" / "build_nuitka_windows.ps1").read_text(encoding="utf-8")

        self.assertIn('$outputExe = Join-Path $outputDir "$appName.exe"', script)
        self.assertIn('$internalDir = Join-Path $outputDir "_internal"', script)
        self.assertIn('Move-Item -Force -LiteralPath $generatedDir -Destination $internalDir', script)
        self.assertIn('New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "data")', script)
        self.assertIn('New-Item -ItemType Directory -Force -Path (Join-Path $outputDir "logs")', script)
        self.assertIn('foreach ($leftover in @("desktop_entry.build", "desktop_entry.dist", "desktop_entry.onefile-build", "data"))', script)
        self.assertNotIn("--onefile", script)

    def test_build_script_icon_is_applied_to_inner_runtime_launcher_and_status_form(self):
        script = (ROOT / "scripts" / "build_nuitka_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("$iconSource = Join-Path $root \"assets\\app-icon.png\"", script)
        self.assertIn("--windows-icon-from-ico=$iconPath", script)
        self.assertIn('/win32icon:"$iconPath"', script)
        self.assertIn("Icon.ExtractAssociatedIcon(Application.ExecutablePath)", script)
        self.assertIn("Application.EnableVisualStyles();", script)

    def test_release_workflow_only_auto_releases_merge_commits_with_code_paths(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        for path in ('"backend/**"', '"frontend/**"', '"scripts/**"', '"package.json"', '"pnpm-lock.yaml"'):
            self.assertIn(path, workflow)
        self.assertNotIn('"README.md"', workflow)
        self.assertIn("Allow only merge commits for automatic releases", workflow)
        self.assertIn('parent_count="$(git show -s --format=%P HEAD | wc -w | tr -d', workflow)
        self.assertIn('if [[ "$parent_count" -ge 2 ]]; then', workflow)
        self.assertIn("reason=not-a-merge-commit", workflow)
        for action in (
            "actions/checkout@v6",
            "actions/setup-node@v6",
            "actions/setup-python@v6",
            "astral-sh/setup-uv@v8.2.0",
            "actions/upload-artifact@v7",
            "softprops/action-gh-release@v3",
        ):
            self.assertIn(action, workflow)
        self.assertIn("package-manager-cache: false", workflow)
        self.assertIn("enable-cache: false", workflow)
        self.assertNotIn("@v2", workflow)
        self.assertNotIn("@v4", workflow)
        self.assertNotIn("@v5", workflow)


if __name__ == "__main__":
    unittest.main()
