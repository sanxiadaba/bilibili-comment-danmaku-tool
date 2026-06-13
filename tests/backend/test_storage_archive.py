import gzip
import json
import logging
import os
import queue
import socket
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path

from helpers import BVID, make_archive, make_comment

from app_logging import BoundedQueueHandler, clean_fields  # noqa: E402
from control_api import control_capabilities, control_openapi_document, normalize_control_action_payload  # noqa: E402
from database_registry import (  # noqa: E402
    import_database_file,
    list_database_catalog,
    parse_multipart_files,
    resolve_database_path,
)
from errors import BadRequestError  # noqa: E402
from progress_state import progress_percent, progress_stats  # noqa: E402
from server import parse_json_object_body  # noqa: E402
from space_archive import (  # noqa: E402
    api_error_response,
    extract_space_mid,
    is_complete,
    should_abort_space_archive,
)
from task_queue import InMemoryTaskQueue  # noqa: E402
from bilibili_comment_danmaku.danmaku import decode_response_body, parse_danmaku_xml  # noqa: E402
from bilibili_comment_danmaku.archive import (  # noqa: E402
    export_archive_to_json,
    export_archive_to_sqlite,
    import_archive_json_to_sqlite,
)
from bilibili_comment_danmaku import scraper  # noqa: E402
from bilibili_comment_danmaku.storage import (  # noqa: E402
    danmaku_user_hash,
    load_comment_data,
    load_danmaku_data,
    list_video_summaries,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)
from bilibili_comment_danmaku.url_utils import extract_bvid  # noqa: E402
class StorageTests(unittest.TestCase):
    def test_comment_refresh_keeps_missing_comments_as_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            reply = make_comment("2", 2, "reply comment", root="1", parent="1", mid="100", like=3)
            top["replies"] = [reply]

            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), db_path, replace=True)
            refreshed_top = make_comment("1", 1, "top comment edited", mid="42", like=9)
            result = save_comments_to_sqlite(
                make_archive("2024-01-02T00:00:00+00:00", [refreshed_top]),
                db_path,
                replace=True,
            )
            loaded = load_comment_data(db_path, bvid=BVID)

            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual(loaded["metadata"]["active_comment_count"], 1)
            self.assertEqual(loaded["metadata"]["deleted_comment_count"], 1)
            by_rpid = {item["normalized"]["rpid"]: item["normalized"] for item in loaded["comment_items"]}
            self.assertFalse(by_rpid["1"]["is_deleted"])
            self.assertTrue(by_rpid["2"]["is_deleted"])
            self.assertEqual(by_rpid["1"]["message"], "top comment edited")
            self.assertTrue(loaded["comments"][0]["normalized"]["is_up_owner"])

    def test_danmaku_save_load_marks_owner_and_builds_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)
            owner_hash = danmaku_user_hash("42")
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "100",
                            "progress": 1.2,
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000001,
                            "pool": 0,
                            "user_hash": owner_hash,
                            "weight": 9,
                            "like_count": 12,
                            "content": "owner danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "101",
                            "progress": 15.0,
                            "mode": 5,
                            "font_size": 25,
                            "color": 0xFE0302,
                            "ctime": 1700000002,
                            "pool": 0,
                            "user_hash": "other",
                            "weight": None,
                            "like_count": 2,
                            "content": "top danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                    ],
                },
                db_path,
                replace=True,
            )

            loaded = load_danmaku_data(db_path, bvid=BVID, limit=1)
            summaries = list_video_summaries(db_path)

            self.assertEqual(loaded["metadata"]["total_count"], 2)
            self.assertEqual(loaded["metadata"]["limit"], 1)
            self.assertEqual(len(loaded["items"]), 1)
            self.assertTrue(loaded["items"][0]["is_up_owner"])
            self.assertEqual([bucket["bucket_start"] for bucket in loaded["buckets"]], [0, 10])
            self.assertEqual(summaries[0]["danmaku_count"], 2)

    def test_export_archive_to_sqlite_creates_independent_subset_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            export_path = Path(tmp) / "exports" / "one_video.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), db_path, replace=True)
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "100",
                            "progress": 1.2,
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000001,
                            "pool": 0,
                            "user_hash": "hash",
                            "weight": 9,
                            "like_count": 12,
                            "content": "danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                    ],
                },
                db_path,
                replace=True,
            )

            result = export_archive_to_sqlite(db_path, export_path, bvids=[BVID])
            summaries = list_video_summaries(export_path)
            comments = load_comment_data(export_path, bvid=BVID)
            danmaku = load_danmaku_data(export_path, bvid=BVID)

            self.assertEqual(result["counts"]["videos"], 1)
            self.assertEqual(result["counts"]["comments"], 1)
            self.assertEqual(result["counts"]["comment_pictures"], 1)
            self.assertEqual(result["counts"]["comment_emotes"], 1)
            self.assertEqual(result["counts"]["danmaku"], 1)
            self.assertEqual(len(summaries), 1)
            self.assertEqual(comments["metadata"]["bvid"], BVID)
            self.assertEqual(comments["comment_items"][0]["normalized"]["pictures"][0]["img_src"], "http://i.example/a.jpg")
            self.assertEqual(danmaku["metadata"]["total_count"], 1)
            self.assertTrue(export_path.exists())
            manifest_path = export_path.with_suffix(".json")
            self.assertEqual(result["json_path"], "")
            self.assertFalse(manifest_path.exists())
            self.assertEqual(result["manifest"]["archive_kind"], "video")
            self.assertEqual(result["manifest"]["bvids"], [BVID])
            self.assertFalse(export_path.with_name(f"{export_path.name}-wal").exists())

    def test_export_archive_to_json_can_be_imported_back_to_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            json_path = Path(tmp) / "exports" / "one_video.json"
            imported_db = Path(tmp) / "imported.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), db_path, replace=True)
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "100",
                            "progress": 1.2,
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000001,
                            "pool": 0,
                            "user_hash": "hash",
                            "weight": 9,
                            "like_count": 12,
                            "content": "danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                    ],
                },
                db_path,
                replace=True,
            )

            result = export_archive_to_json(db_path, json_path, bvids=[BVID])
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            imported = import_archive_json_to_sqlite(json_path, imported_db)
            comments = load_comment_data(imported_db, bvid=BVID)
            danmaku = load_danmaku_data(imported_db, bvid=BVID)

            self.assertTrue(json_path.exists())
            self.assertFalse(json_path.with_suffix(".db").exists())
            self.assertEqual(payload["format"], "bilibili-comment-danmaku-json-data")
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["videos"][0]["metadata"]["bvid"], BVID)
            self.assertEqual(payload["videos"][0]["comments"][0]["normalized"]["message"], "top comment")
            self.assertEqual(payload["videos"][0]["comment_items"][0]["normalized"]["message"], "top comment")
            self.assertEqual(payload["videos"][0]["danmaku"]["items"][0]["content"], "danmaku")
            self.assertEqual(result["json_path"], str(json_path.resolve()))
            self.assertEqual(imported["bvids"], [BVID])
            self.assertEqual(comments["metadata"]["bvid"], BVID)
            self.assertEqual(danmaku["metadata"]["total_count"], 1)

    def test_export_archive_to_sqlite_filters_by_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            export_path = Path(tmp) / "exports" / "owner.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)
            other = make_archive("2024-01-01T00:00:00+00:00", [])
            other["metadata"] = {**other["metadata"], "bvid": "BV1other1111", "aid": 456, "source_url": "https://www.bilibili.com/video/BV1other1111"}
            other["video_raw"] = {**other["video_raw"], "owner": {"mid": "999", "name": "Other", "face": ""}}
            save_comments_to_sqlite(other, db_path, replace=True)

            result = export_archive_to_sqlite(db_path, export_path, owner_mid="42", archive_kind="up", label="Owner")
            summaries = list_video_summaries(export_path)

            self.assertEqual(result["bvids"], [BVID])
            self.assertEqual(result["manifest"]["archive_kind"], "up")
            self.assertEqual(result["manifest"]["label"], "Owner")
            self.assertEqual([item["bvid"] for item in summaries], [BVID])

    def test_database_catalog_detects_hotplug_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            hotplug_db = hotplug_dir / "owner_archive.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), main_db, replace=True)
            export_archive_to_sqlite(main_db, hotplug_db, bvids=[BVID])

            catalog = list_database_catalog(main_db, hotplug_dir)
            by_id = {item["id"]: item for item in catalog}

            self.assertIn("main", by_id)
            self.assertIn("db:owner_archive.db", by_id)
            self.assertEqual(by_id["db:owner_archive.db"]["video_count"], 1)
            self.assertTrue(by_id["db:owner_archive.db"]["ok"])
            self.assertEqual(resolve_database_path("db:owner_archive.db", main_db, hotplug_dir), hotplug_db.resolve())

    def test_database_catalog_ignores_hotplug_json_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            json_path = hotplug_dir / "video_archive.json"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), main_db, replace=True)
            export_archive_to_json(main_db, json_path, bvids=[BVID])

            catalog = list_database_catalog(main_db, hotplug_dir)
            by_id = {item["id"]: item for item in catalog}
            converted_db = hotplug_dir / "video_archive.db"

            self.assertFalse(converted_db.exists())
            self.assertNotIn("db:video_archive.db", by_id)
            self.assertIn("main", by_id)

    def test_database_catalog_marks_duplicate_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            first = hotplug_dir / "first.db"
            second = hotplug_dir / "second.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), main_db, replace=True)
            export_archive_to_sqlite(main_db, first, bvids=[BVID])
            export_archive_to_sqlite(main_db, second, bvids=[BVID])

            catalog = list_database_catalog(main_db, hotplug_dir)
            by_id = {item["id"]: item for item in catalog}

            self.assertEqual(by_id["db:first.db"]["coverage_status"], "duplicate")
            self.assertIn("db:second.db", by_id["db:first.db"]["duplicate_database_ids"])

    def test_database_catalog_marks_archive_with_better_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            small = hotplug_dir / "small.db"
            larger = hotplug_dir / "larger.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), main_db, replace=True)
            export_archive_to_sqlite(main_db, small, bvids=[BVID])

            reply = make_comment("2", 2, "reply comment", root="1", parent="1", mid="100", like=3)
            top["replies"] = [reply]
            save_comments_to_sqlite(make_archive("2024-01-02T00:00:00+00:00", [top]), main_db, replace=True)
            export_archive_to_sqlite(main_db, larger, bvids=[BVID])

            catalog = list_database_catalog(main_db, hotplug_dir)
            by_id = {item["id"]: item for item in catalog}

            self.assertEqual(by_id["db:small.db"]["coverage_status"], "has_better")
            self.assertIn("db:larger.db", by_id["db:small.db"]["better_database_ids"])

    def test_database_path_rejects_traversal_and_bad_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            hotplug_dir.mkdir()
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), main_db, replace=True)
            (hotplug_dir / "notes.txt").write_text("not sqlite", encoding="utf-8")

            with self.assertRaises(BadRequestError):
                resolve_database_path("db:../comment_danmaku.db", main_db, hotplug_dir)
            with self.assertRaises(BadRequestError):
                resolve_database_path("db:notes.txt", main_db, hotplug_dir)

    def test_import_database_file_normalizes_name_and_uses_hotplug_files_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "exports" / "Owner Archive !.sqlite"
            hotplug_dir = root / "databases"
            main_db = root / "comment_danmaku.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), main_db, replace=True)
            export_archive_to_sqlite(main_db, source_db, bvids=[BVID])

            imported = import_database_file(source_db, hotplug_dir)
            imported_again = import_database_file(imported, hotplug_dir)

            self.assertEqual(imported.name, "Owner_Archive.sqlite")
            self.assertEqual(imported_again, imported)
            self.assertEqual(load_comment_data(imported, bvid=BVID)["metadata"]["bvid"], BVID)

    def test_parse_multipart_files_preserves_binary_content(self):
        boundary = "----codex-boundary"
        content = b"\r\nSQLite format 3\x00\npayload\r\n"
        raw = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="archive.db"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

        files = parse_multipart_files(raw, f"multipart/form-data; boundary={boundary}")

        self.assertEqual(files[0]["filename"], "archive.db")
        self.assertEqual(files[0]["content"], content)



