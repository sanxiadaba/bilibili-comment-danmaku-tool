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

    def test_cookie_store_rejects_empty_cookie_and_clears_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt")
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            store.cookie_path.write_text("SESSDATA=secret\n", encoding="utf-8")
            store.backup_dir.mkdir(parents=True, exist_ok=True)
            (store.backup_dir / "cookie-old.txt").write_text("SESSDATA=older-secret\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                store.save("   ")

            with mock.patch("auth_store.inspect_cookie_status") as status:
                status.return_value = {"status": "missing", "exists": False}
                payload = store.clear()

            self.assertFalse(store.cookie_path.exists())
            self.assertEqual(payload["status"], "missing")
            self.assertEqual(list(store.backup_dir.glob("cookie-*.txt")), [])

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

    def test_cookie_store_prunes_old_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = auth_store.CookieStore(Path(tmpdir) / "cookie.txt", backup_limit=2)
            store.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            with mock.patch("auth_store.inspect_cookie_status", return_value={"status": "unchecked", "exists": True}):
                for value in ("one", "two", "three", "four"):
                    store.cookie_path.write_text(f"SESSDATA={value}\n", encoding="utf-8")
                    store.save(f"SESSDATA={value}-new")

            self.assertLessEqual(len(list(store.backup_dir.glob("cookie-*.txt"))), 2)

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
