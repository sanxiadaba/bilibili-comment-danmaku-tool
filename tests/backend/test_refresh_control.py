import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive, make_comment

import progress_state  # noqa: E402
import server as server_module  # noqa: E402
from bilibili_comment_danmaku import scraper  # noqa: E402
from bilibili_comment_danmaku import save_comments_to_sqlite  # noqa: E402
from server import DEFAULT_COMMENT_PAGE_SIZE, CommentDanmakuServer  # noqa: E402


class StopFlagTests(unittest.TestCase):
    def tearDown(self):
        progress_state.clear_stop()

    def test_stop_flag_is_scoped_by_kind(self):
        progress_state.request_stop("comments")

        self.assertTrue(progress_state.is_stop_requested("comments"))
        self.assertFalse(progress_state.is_stop_requested("danmaku"))

    def test_all_flag_covers_every_kind(self):
        progress_state.request_stop("all")

        self.assertTrue(progress_state.is_stop_requested("comments"))
        self.assertTrue(progress_state.is_stop_requested("danmaku"))

    def test_clear_removes_only_the_requested_kind(self):
        progress_state.request_stop("comments")
        progress_state.request_stop("danmaku")

        progress_state.clear_stop("comments")

        self.assertFalse(progress_state.is_stop_requested("comments"))
        self.assertTrue(progress_state.is_stop_requested("danmaku"))

    def test_clear_without_kind_resets_everything(self):
        progress_state.request_stop("comments")
        progress_state.request_stop("danmaku")

        progress_state.clear_stop()

        self.assertFalse(progress_state.is_stop_requested("comments"))
        self.assertFalse(progress_state.is_stop_requested("danmaku"))

    def test_stop_all_does_not_poison_the_next_comment_refresh(self):
        # Regression: a bare "all" flag used to survive clear_stop("comments"), so every later
        # comment refresh aborted on its first page until the process was restarted.
        progress_state.request_stop("all")
        progress_state.clear_stop("comments")

        self.assertFalse(progress_state.is_stop_requested("comments"))


class ScraperStopTests(unittest.TestCase):
    def test_main_reply_loop_stops_before_the_first_request(self):
        class ExplodingClient:
            def request_json(self, *args, **kwargs):
                raise AssertionError("the scraper should not issue a request after a stop request")

        with self.assertRaises(scraper.ScrapeCancelled):
            scraper.fetch_main_replies(
                "2",
                ExplodingClient(),
                "mixin",
                0,
                lambda message: None,
                stop_checker=lambda: True,
            )


class RefreshControlHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.databases = self.root / "databases"
        owner_dir = self.databases / "Owner_42"
        owner_dir.mkdir(parents=True)
        self.db_path = owner_dir / f"{BVID}.db"
        comments = [make_comment(str(index), 1, f"top {index}", mid="42") for index in range(1, 6)]
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", comments), self.db_path, replace=True)
        self.legacy = self.root / "comment_danmaku.db"
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), self.legacy, replace=True)
        handler = type(
            "RefreshControlServer",
            (CommentDanmakuServer,),
            {
                "db_path": self.legacy,
                "database_dir": self.databases,
                "static_dir": self.root / "dist",
                "log_dir": self.root / "logs",
                "log_message": lambda *args, **kwargs: None,
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        progress_state.clear_stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def post(self, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            connection.request(
                "POST",
                path,
                body=json.dumps(payload or {}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://127.0.0.1",
                    "X-Bilibili-Tool-Request": "1",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_stop_endpoint_sets_the_flag(self):
        status, payload = self.post("/api/tasks/stop", {"kind": "comments"})

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(progress_state.is_stop_requested("comments"))

    def test_stop_endpoint_rejects_unknown_kinds(self):
        status, payload = self.post("/api/tasks/stop", {"kind": "everything"})

        self.assertEqual(status, 400)
        self.assertIn("kind", payload["error"])
        self.assertFalse(progress_state.is_stop_requested("comments"))

    def test_refresh_returns_one_page_instead_of_the_whole_archive(self):
        refreshed = make_archive(
            "2024-02-01T00:00:00+00:00",
            [make_comment(str(index), 1, f"refreshed {index}", mid="42") for index in range(1, 8)],
        )
        with mock.patch.object(server_module, "scrape_comments", return_value=refreshed):
            status, payload = self.post(f"/api/refresh?bvid={BVID}")

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["metadata"]["limit"], DEFAULT_COMMENT_PAGE_SIZE)
        self.assertEqual(payload["metadata"]["offset"], 0)
        self.assertLessEqual(len(payload["comment_items"]), DEFAULT_COMMENT_PAGE_SIZE)
        self.assertEqual(payload["refresh"]["after_count"], 7)

    def test_stopped_refresh_keeps_the_stored_archive(self):
        with mock.patch.object(server_module, "scrape_comments", side_effect=scraper.ScrapeCancelled("stop")):
            status, payload = self.post(f"/api/refresh?bvid={BVID}")

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["refresh"]["stopped"])
        self.assertEqual(payload["refresh"]["after_count"], 5)
        self.assertEqual(payload["metadata"]["comment_total_count"], 5)

    def test_stop_flag_is_cleared_after_a_refresh(self):
        refreshed = make_archive(
            "2024-02-01T00:00:00+00:00",
            [make_comment(str(index), 1, f"refreshed {index}", mid="42") for index in range(1, 8)],
        )
        with mock.patch.object(server_module, "scrape_comments", return_value=refreshed):
            self.post(f"/api/refresh?bvid={BVID}")

        self.assertFalse(progress_state.is_stop_requested("comments"))


if __name__ == "__main__":
    unittest.main()
