import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive, make_comment

from auth_store import safe_login_url  # noqa: E402
from app_logging import redact_text  # noqa: E402
from bilibili_comment_danmaku import save_comments_to_sqlite  # noqa: E402
from http_utils import safe_print  # noqa: E402
from server import CommentDanmakuServer, validate_bind_host  # noqa: E402


class LocalHttpTestCase(unittest.TestCase):
    """Runs a real server against a temporary archive so routing/headers are exercised."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.databases = self.root / "databases"
        owner_dir = self.databases / "Owner_42"
        owner_dir.mkdir(parents=True)
        self.db_path = owner_dir / f"{BVID}.db"
        save_comments_to_sqlite(
            make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "top", mid="42")]),
            self.db_path,
            replace=True,
        )
        self.static = self.root / "dist"
        self.static.mkdir()
        (self.static / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
        (self.static / "app.js").write_text("console.log('ok')", encoding="utf-8")
        self.sibling = self.root / "dist_evil"
        self.sibling.mkdir()
        (self.sibling / "secret.txt").write_text("top secret", encoding="utf-8")
        self.legacy = self.root / "comment_danmaku.db"
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), self.legacy, replace=True)

        handler = type(
            "HardeningTestServer",
            (CommentDanmakuServer,),
            {
                "db_path": self.legacy,
                "database_dir": self.databases,
                "static_dir": self.static,
                "log_dir": self.root / "logs",
                "log_message": lambda *args, **kwargs: None,
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            return response.status, response.getheader("Content-Type") or "", payload
        finally:
            connection.close()

    def json_body(self, payload):
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None


class StaticFileTests(LocalHttpTestCase):
    def test_serves_the_spa_shell_for_navigation_routes(self):
        status, content_type, payload = self.request("GET", "/video/BV1xx411c7mD")

        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"<!doctype html>", payload)

    def test_serves_real_assets(self):
        status, content_type, payload = self.request("GET", "/app.js")

        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        self.assertEqual(payload, b"console.log('ok')")

    def test_missing_asset_returns_json_404_instead_of_the_shell(self):
        status, content_type, payload = self.request("GET", "/missing-chunk.js")

        self.assertEqual(status, 404)
        self.assertIn("application/json", content_type)

    def test_sibling_directory_cannot_be_read(self):
        status, _content_type, payload = self.request("GET", "/../dist_evil/secret.txt")

        self.assertEqual(status, 404)
        self.assertNotIn(b"top secret", payload)

    def test_dotdot_into_the_project_cannot_be_read(self):
        status, _content_type, payload = self.request("GET", "/../../package.json")

        self.assertEqual(status, 404)
        self.assertNotIn(b"bilibili-comment-danmaku-tool", payload)


class HostHeaderTests(LocalHttpTestCase):
    def test_get_with_a_foreign_host_is_rejected(self):
        status, content_type, payload = self.request("GET", "/api/videos?limit=1", headers={"Host": "evil.example"})

        self.assertEqual(status, 403)
        self.assertIn("application/json", content_type)
        self.assertIn("本机", self.json_body(payload)["error"])

    def test_get_with_a_local_host_is_allowed(self):
        status, _content_type, payload = self.request(
            "GET",
            "/api/videos?limit=1",
            headers={"Host": f"127.0.0.1:{self.server.server_address[1]}"},
        )

        self.assertEqual(status, 200)
        self.assertIn("videos", self.json_body(payload))

    def test_unknown_post_route_returns_json(self):
        status, content_type, payload = self.request(
            "POST",
            "/api/does-not-exist",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Bilibili-Tool-Request": "1",
            },
        )

        self.assertEqual(status, 404)
        self.assertIn("application/json", content_type)
        self.assertIn("未知 API", self.json_body(payload)["error"])


class BindHostTests(unittest.TestCase):
    def test_loopback_hosts_are_allowed(self):
        for host in ("127.0.0.1", "localhost", "::1", ""):
            self.assertEqual(validate_bind_host(host), host or "127.0.0.1")

    def test_public_bind_is_refused_without_opt_in(self):
        with self.assertRaises(SystemExit):
            validate_bind_host("0.0.0.0")

    def test_public_bind_is_allowed_with_opt_in(self):
        self.assertEqual(validate_bind_host("0.0.0.0", allow_remote=True), "0.0.0.0")


class RedactionTests(unittest.TestCase):
    def test_credentials_are_removed_from_free_text(self):
        text = "cookie: SESSDATA=abc123; bili_jct=csrf456; DedeUserID=42"

        redacted = redact_text(text)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("csrf456", redacted)
        self.assertIn("SESSDATA=***", redacted)
        self.assertIn("DedeUserID=***", redacted)

    def test_plain_text_is_untouched(self):
        self.assertEqual(redact_text("comment refresh finished"), "comment refresh finished")
        self.assertIsNone(redact_text(None))

    def test_login_url_loses_query_and_fragment(self):
        self.assertEqual(
            safe_login_url("https://passport.bilibili.com/login?token=secret#frag"),
            "https://passport.bilibili.com/login",
        )
        self.assertEqual(safe_login_url(""), "")

    def test_safe_print_survives_a_missing_stdout(self):
        with mock.patch.object(sys, "stdout", None):
            safe_print("should not raise")


if __name__ == "__main__":
    unittest.main()
