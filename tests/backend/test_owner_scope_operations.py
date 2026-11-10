import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from helpers import BVID, make_archive, make_comment

from bilibili_comment_danmaku import (  # noqa: E402
    export_archive_from_databases,
    list_video_summaries_page,
    save_comments_to_sqlite,
)
from database_registry import (  # noqa: E402
    owner_video_database_sources,
    video_database_sources,
)
from server import CommentDanmakuServer, is_aggregate_database_scope  # noqa: E402

OTHER_BVID = "BV1other1111"


def other_archive(owner_mid="43", owner_name="Other", bvid=OTHER_BVID, fetched_at="2024-01-02T00:00:00+00:00"):
    archive = make_archive(fetched_at, [make_comment("9", 1, f"top {bvid}", mid=owner_mid)])
    archive["metadata"] = {
        **archive["metadata"],
        "bvid": bvid,
        "aid": 456,
        "source_url": f"https://www.bilibili.com/video/{bvid}",
    }
    archive["video_raw"] = {**archive["video_raw"], "owner": {"mid": owner_mid, "name": owner_name, "face": ""}}
    return archive


def build_two_database_layout(root):
    """Two per-video databases under different owner folders, mimicking the real archive layout."""
    databases = root / "databases"
    first = databases / "Owner_42" / f"{BVID}.db"
    second = databases / "Other_43" / f"{OTHER_BVID}.db"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    save_comments_to_sqlite(
        make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "top comment", mid="42", like=8)]),
        first,
        replace=True,
    )
    save_comments_to_sqlite(other_archive(), second, replace=True)
    return databases, first, second


class VideoSourceResolutionTests(unittest.TestCase):
    def test_resolves_each_requested_bvid_to_its_own_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            databases, first, second = build_two_database_layout(Path(tmp))

            sources, missing = video_database_sources([BVID, OTHER_BVID], databases)

            self.assertEqual(missing, [])
            self.assertEqual(dict(sources), {first.resolve(): [BVID], second.resolve(): [OTHER_BVID]})

    def test_reports_bvids_that_are_not_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            databases, _first, _second = build_two_database_layout(Path(tmp))

            sources, missing = video_database_sources([BVID, "BV1missing111"], databases)

            self.assertEqual(len(sources), 1)
            self.assertEqual(missing, ["BV1missing111"])

    def test_falls_back_to_the_legacy_single_file_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            databases = root / "databases"
            databases.mkdir()
            legacy = root / "comment_danmaku.db"
            save_comments_to_sqlite(
                make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "legacy comment", mid="42")]),
                legacy,
                replace=True,
            )

            sources, missing = video_database_sources([BVID], databases, fallback_db_path=legacy)

            self.assertEqual(missing, [])
            self.assertEqual(dict(sources), {legacy.resolve(): [BVID]})

    def test_owner_sources_span_every_catalog_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            databases = root / "databases"
            first = databases / "Owner_42" / f"{BVID}.db"
            second = databases / "Owner_42_renamed" / f"{OTHER_BVID}.db"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            save_comments_to_sqlite(
                make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "top comment", mid="42")]),
                first,
                replace=True,
            )
            save_comments_to_sqlite(other_archive(owner_mid="42", owner_name="Owner", bvid=OTHER_BVID), second, replace=True)

            sources = owner_video_database_sources("42", databases)

            self.assertEqual(dict(sources), {first.resolve(): [BVID], second.resolve(): [OTHER_BVID]})

    def test_owner_sources_ignore_databases_without_that_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            databases, _first, _second = build_two_database_layout(Path(tmp))

            self.assertEqual(owner_video_database_sources("999", databases), [])


class MergedExportTests(unittest.TestCase):
    def test_merges_videos_from_separate_databases_into_one_sqlite_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            databases, first, _second = build_two_database_layout(root)
            sources, missing = video_database_sources([BVID, OTHER_BVID], databases)
            self.assertEqual(missing, [])
            target = root / "exports" / "merged.db"

            result = export_archive_from_databases(sources, target, archive_kind="collection", label="merged")

            summaries = list_video_summaries_page(target, limit=10)["videos"]
            self.assertEqual(result["counts"]["videos"], 2)
            self.assertEqual(result["counts"]["comments"], 2)
            self.assertEqual(result["counts"]["danmaku"], 0)
            self.assertEqual({video["bvid"] for video in summaries}, {BVID, OTHER_BVID})
            self.assertEqual(result["manifest"]["archive_kind"], "collection")
            self.assertEqual(sorted(result["manifest"]["bvids"]), sorted([BVID, OTHER_BVID]))
            self.assertEqual(len(result["manifest"]["videos"]), 2)
            self.assertTrue(target.exists())
            # The source databases must stay untouched: export must not move or delete originals.
            self.assertEqual(len(list_video_summaries_page(first, limit=10)["videos"]), 1)

    def test_merged_export_of_one_owner_is_marked_as_up_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            databases, _first, _second = build_two_database_layout(root)
            sources = owner_video_database_sources("42", databases)
            target = root / "exports" / "owner.db"

            result = export_archive_from_databases(
                sources,
                target,
                archive_kind="up",
                label="Owner",
                owner_mid="42",
            )

            self.assertEqual(result["manifest"]["archive_kind"], "up")
            self.assertEqual(result["manifest"]["owner_mid"], "42")
            self.assertEqual(result["manifest"]["label"], "Owner")
            self.assertEqual(result["bvids"], [BVID])

    def test_merged_export_writes_importable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            databases, _first, _second = build_two_database_layout(root)
            sources, _missing = video_database_sources([BVID, OTHER_BVID], databases)
            target = root / "exports" / "merged.json"

            result = export_archive_from_databases(sources, target, export_format="json", label="merged")

            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], "bilibili-comment-danmaku-json-data")
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual({item["bvid"] for item in payload["videos"]}, {BVID, OTHER_BVID})
            self.assertEqual(result["json_path"], str(target.resolve()))
            self.assertEqual(result["counts"]["videos"], 2)

    def test_merged_export_rejects_empty_source_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LookupError):
                export_archive_from_databases([], Path(tmp) / "empty.db")


class AggregateScopeHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.databases, self.first_database, self.second_database = build_two_database_layout(self.root)
        self.legacy = self.root / "comment_danmaku.db"
        save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), self.legacy, replace=True)
        handler = type(
            "ReviewServer",
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
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def post(self, path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.request(
                "POST",
                path,
                body=json.dumps(payload).encode("utf-8"),
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

    def test_aggregate_scope_detection(self):
        self.assertTrue(is_aggregate_database_scope(None))
        self.assertTrue(is_aggregate_database_scope(""))
        self.assertTrue(is_aggregate_database_scope("main"))
        self.assertFalse(is_aggregate_database_scope("db:Owner_42/" + f"{BVID}.db"))

    def test_delete_from_the_aggregate_view_is_rejected(self):
        status, payload = self.post("/api/archive/delete", {"bvid": BVID})

        self.assertEqual(status, 400)
        self.assertIn("聚合视图", payload["error"])
        # The archived video must survive a rejected aggregate delete.
        self.assertEqual(len(list_video_summaries_page(self.first_database, limit=10)["videos"]), 1)

    def test_export_from_the_aggregate_view_reads_the_per_video_database(self):
        status, payload = self.post("/api/database/export", {"bvid": BVID, "format": "sqlite"})

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["video_count"], 1)
        self.assertEqual(payload["counts"]["videos"], 1)
        self.assertEqual(payload["counts"]["comments"], 1)
        exported = Path(payload["path"])
        self.assertTrue(exported.exists())
        self.assertEqual([video["bvid"] for video in list_video_summaries_page(exported, limit=10)["videos"]], [BVID])

    def test_export_from_the_aggregate_view_covers_one_owner(self):
        status, payload = self.post("/api/database/export", {"owner_mid": "42", "format": "sqlite"})

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["video_count"], 1)
        self.assertEqual(payload["manifest"]["archive_kind"], "up")


if __name__ == "__main__":
    unittest.main()
