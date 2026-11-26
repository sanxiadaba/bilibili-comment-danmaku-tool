import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import auth_store  # noqa: E402


class AuthStoreTests(unittest.TestCase):
    def test_cookie_store_saves_plain_or_netscape_cookie_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "unchecked", "exists": True}

                payload = store.save(
                    "# Netscape HTTP Cookie File\n"
                    ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tsecret-session\n"
                    ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\tsecret-csrf\n"
                )

            self.assertEqual(payload["status"], "unchecked")
            self.assertEqual(store.cookie_path.read_text(encoding="utf-8").strip(), "SESSDATA=secret-session; bili_jct=secret-csrf")

    def test_cookie_store_saves_httponly_netscape_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "unchecked", "exists": True}

                store.save(
                    "# Netscape HTTP Cookie File\n"
                    "#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret-session\n"
                    ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\tsecret-csrf\n"
                )

            self.assertEqual(
                store.cookie_path.read_text(encoding="utf-8").strip(),
                "SESSDATA=secret-session; bili_jct=secret-csrf",
            )

    def test_normalize_cookie_text_strips_cookie_prefix_from_pasted_header(self):
        self.assertEqual(
            auth_store.normalize_cookie_text("Cookie: SESSDATA=abc; bili_jct=def"),
            "SESSDATA=abc; bili_jct=def",
        )

    def test_normalize_cookie_text_rejects_lookalike_domains(self):
        self.assertEqual(auth_store.normalize_cookie_text("evilbilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tx"), "")

    def test_cookie_store_rejects_empty_cookie_and_clears_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=secret\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                store.save("   ")

            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "missing", "exists": False}
                payload = store.clear()

            self.assertFalse(store.cookie_path.exists())
            self.assertEqual(payload["status"], "missing")
            # Logging out must not leave a plaintext copy of the cookie behind.
            backups = list(store.backup_dir.glob("cookie-*.txt"))
            self.assertEqual(backups, [])

    def test_cookie_status_reuses_a_recent_remote_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=secret\n", encoding="utf-8")

            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "valid", "exists": True}

                first = store.status(check_remote=True)
                second = store.status(check_remote=True)

            self.assertEqual(first["status"], "valid")
            self.assertEqual(second["status"], "valid")
            # Two page loads within the cache window probe Bilibili once.
            self.assertEqual(status.call_count, 1)

    def test_cookie_store_backs_up_existing_cookie_before_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=old\n", encoding="utf-8")

            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "unchecked", "exists": True}
                store.save("SESSDATA=new")

            backups = list(store.backup_dir.glob("cookie-*.txt"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "SESSDATA=old\n")
            self.assertEqual(store.cookie_path.read_text(encoding="utf-8").strip(), "SESSDATA=new")

    def test_backup_existing_returns_the_backup_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=old\n", encoding="utf-8")

            backup_path, error = store.backup_existing()

            self.assertEqual(error, "")
            self.assertIsNotNone(backup_path)
            self.assertEqual(backup_path.read_text(encoding="utf-8"), "SESSDATA=old\n")

    def test_cookie_store_reports_backup_failure_but_still_saves(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = auth_store.CookieStore(root / "cookie.txt", backup_dir=root / "blocked-backup")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=old\n", encoding="utf-8")
            # 用一个同名文件占住备份目录，mkdir 必然失败，模拟磁盘/权限问题。
            store.backup_dir.write_text("not a directory", encoding="utf-8")

            backup_path, error = store.backup_existing()
            self.assertIsNone(backup_path)
            self.assertTrue(error)

            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "unchecked", "exists": True}
                with mock.patch("auth_store.log_event") as log_event:
                    payload = store.save("SESSDATA=new")

            self.assertEqual(payload["status"], "unchecked")
            self.assertIn("backup_warning", payload)
            self.assertTrue(payload["backup_warning"])
            log_event.assert_called_once()
            self.assertEqual(store.cookie_path.read_text(encoding="utf-8").strip(), "SESSDATA=new")

    def test_qr_login_success_persists_response_cookies(self):
        headers = Message()
        headers.add_header("Set-Cookie", "SESSDATA=session-value; Path=/; Domain=.bilibili.com")
        headers.add_header("Set-Cookie", "bili_jct=csrf-value; Path=/; Domain=.bilibili.com")

        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            service = auth_store.BilibiliQrLoginService(store)

            with mock.patch("auth_store.request_json_with_cookies") as request, mock.patch.object(
                store,
                "status",
                return_value={"status": "valid", "is_login": True},
            ):
                request.side_effect = [
                    (
                        {
                            "code": 0,
                            "data": {
                                "qrcode_key": "qr-key",
                                "url": "https://passport.bilibili.com/qrcode",
                            },
                        },
                        Message(),
                    ),
                    (
                        {
                            "code": 0,
                            "data": {
                                "code": 0,
                                "message": "登录成功",
                                "url": "https://www.bilibili.com",
                            },
                        },
                        headers,
                    ),
                ]

                session = service.create_session()
                payload = service.poll(session["session_id"])

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "confirmed")
            self.assertEqual(store.cookie_path.read_text(encoding="utf-8").strip(), "SESSDATA=session-value; bili_jct=csrf-value")


if __name__ == "__main__":
    unittest.main()
