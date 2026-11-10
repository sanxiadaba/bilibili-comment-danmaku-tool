import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive, make_comment

import server as server_module  # noqa: E402
from bilibili_comment_danmaku import load_comment_data, save_comments_to_sqlite, storage  # noqa: E402
from bilibili_comment_danmaku.storage import (  # noqa: E402
    MAX_VIDEO_LIST_LIMIT,
    SCHEMA_VERSION,
    connect,
    list_video_summaries_page,
)
from database_registry import list_all_video_summaries_page  # noqa: E402
from server import CommentDanmakuServer, should_skip_comment_refresh  # noqa: E402


def seed_videos(db_path, count):
    bvids = [f"BV{index:010d}" for index in range(count)]
    conn = connect(db_path)
    try:
        storage.ensure_schema(conn)
        conn.executemany(
            """
            INSERT OR REPLACE INTO videos (
                bvid, aid, title, source_url, fetched_at, comment_total_count, owner_mid, owner_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bvid,
                    index,
                    f"video {index}",
                    f"https://www.bilibili.com/video/{bvid}",
                    f"2024-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
                    0,
                    "42",
                    "Owner",
                )
                for index, bvid in enumerate(bvids)
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return bvids


class AggregatePaginationTests(unittest.TestCase):
    def test_aggregate_listing_reads_past_the_single_database_page_cap(self):
        count = MAX_VIDEO_LIST_LIMIT + 50
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            databases = root / "databases" / "Collection"
            databases.mkdir(parents=True)
            big_db = databases / "collection.db"
            seed_videos(big_db, count)

            first = list_all_video_summaries_page(main_db, root / "databases", limit=40, offset=0)
            deep = list_all_video_summaries_page(main_db, root / "databases", limit=40, offset=200)

            self.assertEqual(first["total"], count)
            self.assertEqual(len(first["videos"]), 40)
            self.assertEqual(len(deep["videos"]), 40)
            self.assertTrue(deep["has_more"])
            self.assertEqual(len({item["bvid"] for item in first["videos"] + deep["videos"]}), 80)

    def test_public_page_cap_is_still_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "big.db"
            seed_videos(db_path, MAX_VIDEO_LIST_LIMIT + 10)

            page = list_video_summaries_page(db_path, limit=5000, offset=0)

            self.assertEqual(page["limit"], MAX_VIDEO_LIST_LIMIT)
            self.assertEqual(len(page["videos"]), MAX_VIDEO_LIST_LIMIT)


class PageMediaScopeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "archive.db"
        comments = [make_comment(str(index), 1, f"top {index}", mid="42") for index in range(1, 4)]
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", comments), self.db_path, replace=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_paged_load_only_fetches_media_for_the_page(self):
        with mock.patch.object(storage, "load_pictures_by_rpid", wraps=storage.load_pictures_by_rpid) as pictures:
            load_comment_data(self.db_path, bvid=BVID, limit=1, offset=0)

        rpids = pictures.call_args.kwargs.get("rpids")
        self.assertIsNotNone(rpids)
        self.assertEqual(len(rpids), 1)

    def test_full_load_still_fetches_media_for_the_whole_video(self):
        with mock.patch.object(storage, "load_pictures_by_rpid", wraps=storage.load_pictures_by_rpid) as pictures:
            payload = load_comment_data(self.db_path, bvid=BVID)

        self.assertIsNone(pictures.call_args.kwargs.get("rpids"))
        self.assertEqual(len(payload["comment_items"]), 3)


class SchemaMigrationTests(unittest.TestCase):
    def test_migration_runs_once_per_file_then_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "archive.db"
            comments = [make_comment("1", 1, "top", mid="42")]
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", comments), db_path, replace=True)
            conn = connect(db_path)
            conn.execute("PRAGMA user_version = 0")
            conn.commit()
            conn.close()

            with mock.patch.object(storage, "ensure_schema", wraps=storage.ensure_schema) as migrated:
                load_comment_data(db_path, bvid=BVID)
                load_comment_data(db_path, bvid=BVID)

            self.assertEqual(migrated.call_count, 1)

            conn = connect(db_path)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            finally:
                conn.close()

    def test_current_schema_files_are_never_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "archive.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)

            with mock.patch.object(storage, "ensure_schema", wraps=storage.ensure_schema) as migrated:
                load_comment_data(db_path, bvid=BVID)

            self.assertEqual(migrated.call_count, 0)


class CommentRefreshGuardTests(unittest.TestCase):
    def test_guard_treats_empty_and_tiny_results_as_partial(self):
        self.assertFalse(should_skip_comment_refresh(0, 0))
        self.assertFalse(should_skip_comment_refresh(10, 0))
        self.assertTrue(should_skip_comment_refresh(0, 100))
        self.assertTrue(should_skip_comment_refresh(3, 100))
        self.assertTrue(should_skip_comment_refresh(49, 100))
        self.assertFalse(should_skip_comment_refresh(50, 100))
        self.assertFalse(should_skip_comment_refresh(120, 100))
        self.assertFalse(should_skip_comment_refresh("bad", 100))


class CommentRefreshHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.databases = self.root / "databases"
        self.database_dir = self.databases / "Owner_42"
        self.database_dir.mkdir(parents=True)
        self.db_path = self.database_dir / f"{BVID}.db"
        comments = [make_comment(str(index), 1, f"top {index}", mid="42") for index in range(1, 21)]
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", comments), self.db_path, replace=True)
        self.legacy = self.root / "comment_danmaku.db"
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), self.legacy, replace=True)
        handler = type(
            "RefreshTestServer",
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
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def post(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        try:
            connection.request(
                "POST",
                path,
                body=b"{}",
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

    def test_partial_scrape_keeps_the_stored_comments(self):
        tiny = make_archive("2024-02-01T00:00:00+00:00", [make_comment("999", 1, "only one", mid="42")])
        with mock.patch.object(server_module, "scrape_comments", return_value=tiny):
            status, payload = self.post(f"/api/refresh?bvid={BVID}")

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["refresh"]["skipped"])
        self.assertEqual(payload["refresh"]["scraped_count"], 1)
        self.assertEqual(payload["refresh"]["after_count"], 20)
        self.assertEqual(payload["metadata"]["comment_total_count"], 20)
        stored = load_comment_data(self.db_path, bvid=BVID)
        self.assertEqual(len(stored["comment_items"]), 20)

    def test_healthy_scrape_is_saved(self):
        full = make_archive(
            "2024-02-01T00:00:00+00:00",
            [make_comment(str(index), 1, f"refresh {index}", mid="42") for index in range(1, 26)],
        )
        with mock.patch.object(server_module, "scrape_comments", return_value=full):
            status, payload = self.post(f"/api/refresh?bvid={BVID}")

        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["refresh"].get("skipped", False))
        self.assertEqual(payload["refresh"]["after_count"], 25)

    def test_force_flag_overrides_the_guard(self):
        tiny = make_archive("2024-02-01T00:00:00+00:00", [make_comment("999", 1, "only one", mid="42")])
        with mock.patch.object(server_module, "scrape_comments", return_value=tiny):
            status, payload = self.post(f"/api/refresh?bvid={BVID}&force=1")

        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["refresh"].get("skipped", False))
        # Replacing keeps history: the 20 old rows stay as deleted, the new one is active.
        self.assertEqual(payload["refresh"]["after_count"], 21)
        self.assertEqual(payload["refresh"]["active_count"], 1)
        self.assertEqual(payload["refresh"]["deleted_count"], 20)


if __name__ == "__main__":
    unittest.main()
