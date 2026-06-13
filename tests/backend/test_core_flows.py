import gzip
import json
import logging
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app_logging import BoundedQueueHandler, clean_fields  # noqa: E402
from control_api import control_capabilities, normalize_control_action_payload  # noqa: E402
from database_registry import (  # noqa: E402
    import_database_file,
    list_database_catalog,
    parse_multipart_files,
    resolve_database_path,
)
from errors import BadRequestError  # noqa: E402
from progress_state import progress_percent, progress_stats  # noqa: E402
from server import (  # noqa: E402
    parse_json_object_body,
)
from space_archive import (  # noqa: E402
    api_error_response,
    extract_space_mid,
    is_complete,
    should_abort_space_archive,
)
from task_queue import InMemoryTaskQueue  # noqa: E402
from bilibili_comment_danmaku.danmaku import (  # noqa: E402
    decode_response_body,
    parse_danmaku_xml,
)
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


BVID = "BV1xx411c7mD"


def make_comment(rpid, level, message, *, root="0", parent="0", mid="100", like=0, ctime=1700000000):
    return {
        "normalized": {
            "level": level,
            "rpid": str(rpid),
            "oid": "123",
            "type": 1,
            "mid": str(mid),
            "root": str(root),
            "parent": str(parent),
            "dialog": "0",
            "ctime": ctime,
            "time_iso": "2024-01-01T00:00:00+08:00",
            "time_iso_utc": "2023-12-31T16:00:00+00:00",
            "like": like,
            "rcount": 1 if level == 1 else 0,
            "count": 1 if level == 1 else 0,
            "state": 0,
            "attr": 0,
            "message": message,
            "ip_location": "IP属地：上海",
            "pictures": [
                {
                    "img_src": "http://i.example/a.jpg",
                    "img_width": 640,
                    "img_height": 480,
                    "img_size": 12.5,
                    "play_gif_thumbnail": False,
                }
            ]
            if level == 1
            else [],
            "emote": {
                "[doge]": {
                    "url": "http://i.example/doge.png",
                    "jump_title": "doge",
                    "meta": {"size": 1},
                    "package_id": 1,
                    "type": 1,
                }
            }
            if level == 1
            else {},
            "user": {
                "mid": str(mid),
                "uname": f"user-{mid}",
                "sex": "保密",
                "sign": "hello",
                "avatar": "http://i.example/avatar.jpg",
                "level": 5,
            },
        },
        "raw": {},
        "replies": [],
    }


def make_archive(fetched_at, comments):
    return {
        "metadata": {
            "bvid": BVID,
            "aid": 123,
            "title": "测试视频",
            "source_url": f"https://www.bilibili.com/video/{BVID}",
            "fetched_at": fetched_at,
            "sort": "like",
            "api_comment_count": len(comments),
            "top_level_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 1),
            "expected_nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "comment_total_count": len(comments),
        },
        "video_raw": {
            "cid": "456",
            "pic": "http://i.example/pic.jpg",
            "owner": {"mid": "42", "name": "UP主", "face": "http://i.example/up.jpg"},
            "stat": {"view": 1000, "danmaku": 2, "reply": 2, "favorite": 1, "coin": 2, "share": 3, "like": 4},
            "pubdate": 1700000000,
            "desc": "desc",
            "duration": 180,
        },
        "comments": comments,
    }


class UrlAndDanmakuTests(unittest.TestCase):
    def test_extract_bvid_from_plain_text_and_url(self):
        self.assertEqual(extract_bvid(BVID), BVID)
        self.assertEqual(extract_bvid(f"https://www.bilibili.com/video/{BVID}/?p=1"), BVID)
        with self.assertRaises(ValueError):
            extract_bvid("not a bilibili video")

    def test_decode_response_body_supports_plain_gzip_and_deflate(self):
        payload = b"<i><d p='1,1,25,16777215,1700000000,0,hash,1'>hi</d></i>"
        self.assertEqual(decode_response_body(payload, ""), payload)
        self.assertEqual(decode_response_body(gzip.compress(payload), "gzip"), payload)
        self.assertEqual(decode_response_body(zlib.compress(payload), "deflate"), payload)

    def test_parse_danmaku_xml_skips_invalid_rows_and_unescapes_content(self):
        xml = b"""
        <i>
          <d p="12.5,1,25,16777215,1700000000,0,abc,100,9">hello &amp; hi</d>
          <d p="bad,row">skip</d>
        </i>
        """
        rows = parse_danmaku_xml(xml, BVID, "456")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dmid"], "100")
        self.assertEqual(rows[0]["progress"], 12.5)
        self.assertEqual(rows[0]["weight"], 9)
        self.assertEqual(rows[0]["content"], "hello & hi")


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


class ScraperPerformanceTests(unittest.TestCase):
    def test_child_fetch_batch_removes_serial_root_spacing(self):
        class FakeClient:
            def clone(self):
                return self

            def request_json(self, _url, **_kwargs):
                return {
                    "data": {
                        "replies": [
                            {
                                "rpid_str": "2",
                                "oid_str": "123",
                                "type": 1,
                                "mid_str": "100",
                                "root_str": "1",
                                "parent_str": "1",
                                "dialog_str": "0",
                                "ctime": 1700000001,
                                "like": 1,
                                "rcount": 0,
                                "count": 0,
                                "state": 0,
                                "attr": 0,
                                "content": {"message": "child"},
                                "member": {"mid": "100", "uname": "user-100"},
                            }
                        ],
                        "page": {"count": 1},
                    }
                }

        main_reply = {
            "rpid_str": "1",
            "oid_str": "123",
            "type": 1,
            "mid_str": "42",
            "root_str": "0",
            "parent_str": "0",
            "dialog_str": "0",
            "ctime": 1700000000,
            "like": 8,
            "rcount": 1,
            "count": 1,
            "state": 0,
            "attr": 0,
            "content": {"message": "parent"},
            "member": {"mid": "42", "uname": "owner"},
        }
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            comments, comment_items, summary = scraper.build_threaded_output(
                [main_reply],
                "123",
                FakeClient(),
                0.35,
                lambda _message: None,
            )
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comment_items), 2)
        self.assertEqual(summary[0]["fetched_count"], 1)
        self.assertEqual(sleeps, [])

    def test_child_fetch_batch_fetches_multiple_roots_and_reports_totals(self):
        class FakeClient:
            def clone(self):
                return self

            def request_json(self, url, **_kwargs):
                root = "1" if "root=1" in url else "3"
                child_rpid = "2" if root == "1" else "4"
                return {
                    "data": {
                        "replies": [
                            {
                                "rpid_str": child_rpid,
                                "oid_str": "123",
                                "type": 1,
                                "mid_str": "100",
                                "root_str": root,
                                "parent_str": root,
                                "dialog_str": "0",
                                "ctime": 1700000001,
                                "like": 1,
                                "rcount": 0,
                                "count": 0,
                                "state": 0,
                                "attr": 0,
                                "content": {"message": f"child {child_rpid}"},
                                "member": {"mid": "100", "uname": "user-100"},
                            }
                        ],
                        "page": {"count": 1},
                    }
                }

        replies = [
            {
                "rpid_str": "1",
                "oid_str": "123",
                "type": 1,
                "mid_str": "42",
                "root_str": "0",
                "parent_str": "0",
                "dialog_str": "0",
                "ctime": 1700000000,
                "like": 8,
                "rcount": 1,
                "count": 1,
                "state": 0,
                "attr": 0,
                "content": {"message": "parent 1"},
                "member": {"mid": "42", "uname": "owner"},
            },
            {
                "rpid_str": "3",
                "oid_str": "123",
                "type": 1,
                "mid_str": "43",
                "root_str": "0",
                "parent_str": "0",
                "dialog_str": "0",
                "ctime": 1700000002,
                "like": 7,
                "rcount": 1,
                "count": 1,
                "state": 0,
                "attr": 0,
                "content": {"message": "parent 2"},
                "member": {"mid": "43", "uname": "user-43"},
            },
        ]
        logs = []
        comments, comment_items, summary = scraper.build_threaded_output(
            replies,
            "123",
            FakeClient(),
            0,
            logs.append,
        )

        self.assertEqual(len(comments), 2)
        self.assertEqual(len(comment_items), 4)
        self.assertEqual([item["fetched_count"] for item in summary], [1, 1])
        self.assertTrue(any("fetching children batch: roots=2 workers=2" in item for item in logs))
        self.assertTrue(any("total_fetched=2 total_expected=2" in item for item in logs))

    def test_comment_page_spacing_uses_short_yields_and_periodic_full_delay(self):
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            for page in (1, 2, 20, 21):
                scraper.sleep_between_pages(0.35, page)
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(sleeps, [0.02, 0.02, 0.35, 0.02])

    def test_child_page_spacing_uses_gentler_yields_and_periodic_full_delay(self):
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            for page in (1, 2, 10, 11):
                scraper.sleep_between_child_pages(0.35, page)
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(sleeps, [0.12, 0.12, 0.35, 0.12])

    def test_signed_request_refreshes_signature_after_blocked_status(self):
        class FakeBackoff:
            def __init__(self):
                self.blocks = []

            def block_for(self, seconds):
                self.blocks.append(seconds)

        class FakeClient:
            def __init__(self):
                self.urls = []
                self.backoff = FakeBackoff()

            def request_json(self, url, retries=1, **_kwargs):
                self.urls.append(url)
                if len(self.urls) == 1:
                    raise scraper.BilibiliRequestError("blocked", status=412, url=url)
                return {"data": {"ok": True}}

        sleeps = []
        times = iter([1000, 1030])
        original_sleep = scraper.time.sleep
        original_time = scraper.time.time
        original_uniform = scraper.random.uniform
        try:
            scraper.time.sleep = sleeps.append
            scraper.time.time = lambda: next(times)
            scraper.random.uniform = lambda _start, _end: 5
            client = FakeClient()
            mixin_keys = iter(["1" * 32])
            result = scraper.request_signed_json(
                "https://example.test/reply",
                lambda: {"oid": 1, "next": 0},
                client,
                "0" * 32,
                lambda _message: None,
                refresh_mixin_key=lambda: next(mixin_keys),
            )
        finally:
            scraper.time.sleep = original_sleep
            scraper.time.time = original_time
            scraper.random.uniform = original_uniform

        self.assertEqual(result, {"data": {"ok": True}})
        self.assertEqual(sleeps, [17])
        self.assertEqual(client.backoff.blocks, [17])
        self.assertEqual(len(client.urls), 2)
        self.assertIn("wts=1000", client.urls[0])
        self.assertIn("wts=1030", client.urls[1])
        self.assertNotEqual(client.urls[0], client.urls[1])
        self.assertNotIn("w_rid=" + client.urls[0].split("w_rid=", 1)[1], client.urls[1])

    def test_signed_request_passes_logger_to_client_request(self):
        calls = []

        class FakeClient:
            def request_json(self, url, retries=1, logger=None, **_kwargs):
                calls.append({"url": url, "retries": retries, "logger": logger})
                return {"data": {"ok": True}}

        def log(_message):
            pass

        result = scraper.request_signed_json(
            "https://example.test/reply",
            lambda: {"oid": 1, "next": 0},
            FakeClient(),
            "0" * 32,
            log,
        )

        self.assertEqual(result, {"data": {"ok": True}})
        self.assertIs(calls[0]["logger"], log)

    def test_retry_delay_distinguishes_session_retry_from_rate_limit(self):
        original_uniform = scraper.random.uniform
        try:
            scraper.random.uniform = lambda _start, _end: 5

            self.assertEqual(scraper.retry_delay_seconds(1, status=412), 17)
            self.assertEqual(scraper.retry_delay_seconds(1, status=429), 185)
            self.assertEqual(scraper.retry_delay_seconds(1, api_code=-352), 185)
        finally:
            scraper.random.uniform = original_uniform

    def test_retry_after_seconds_reads_header(self):
        class FakeError:
            headers = {"Retry-After": "123"}

        class BadHeaderError:
            headers = {"Retry-After": "later"}

        self.assertEqual(scraper.retry_after_seconds(FakeError()), 123)
        self.assertIsNone(scraper.retry_after_seconds(BadHeaderError()))

    def test_client_seeds_cookie_jar_from_cookie_header(self):
        client = scraper.BilibiliClient(
            scraper.make_headers(BVID, "SESSDATA=session-value; bili_jct=csrf-value"),
            use_proxy=False,
        )
        cookies = {cookie.name: cookie.value for cookie in client.cookie_jar}

        self.assertNotIn("Cookie", client.headers)
        self.assertEqual(cookies["SESSDATA"], "session-value")
        self.assertEqual(cookies["bili_jct"], "csrf-value")

    def test_cookie_browser_identifier_detection(self):
        self.assertTrue(scraper.cookie_has_browser_identifiers("SESSDATA=a; buvid3=b; bili_jct=c"))
        self.assertFalse(scraper.cookie_has_browser_identifiers("SESSDATA=a; bili_jct=c"))

    def test_api_block_code_is_treated_as_blocked_request(self):
        exc = scraper.BilibiliRequestError("blocked", api_code=-352, url="https://example.test")

        self.assertTrue(scraper.is_blocked_request_error(exc))
        self.assertEqual(scraper.blocked_error_label(exc), "API code -352")

    def test_consecutive_very_slow_requests_trigger_long_cooldown(self):
        original_uniform = scraper.random.uniform
        original_monotonic = scraper.time.monotonic
        try:
            scraper.random.uniform = lambda start, _end: start
            now = [1000]
            scraper.time.monotonic = lambda: now[0]
            backoff = scraper.RequestBackoff(persist=False)

            self.assertEqual(backoff.note_slow_request(120), 0)
            now[0] += 100
            self.assertEqual(backoff.note_slow_request(120), 0)
            now[0] += 100
            cooldown = backoff.note_slow_request(120)
            blocked_for = round(backoff.blocked_until - now[0])
        finally:
            scraper.random.uniform = original_uniform
            scraper.time.monotonic = original_monotonic

        self.assertEqual(cooldown, scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0])
        self.assertEqual(blocked_for, scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0])

    def test_repeated_slow_limit_escalates_cooldown_during_recovery_window(self):
        original_uniform = scraper.random.uniform
        original_monotonic = scraper.time.monotonic
        try:
            scraper.random.uniform = lambda start, _end: start
            now = [1000]
            scraper.time.monotonic = lambda: now[0]
            backoff = scraper.RequestBackoff(persist=False)

            backoff.note_slow_request(120)
            now[0] += 100
            backoff.note_slow_request(120)
            now[0] += 100
            first_cooldown = backoff.note_slow_request(120)
            now[0] += scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0] + 60
            second_cooldown = backoff.note_slow_request(120)
        finally:
            scraper.random.uniform = original_uniform
            scraper.time.monotonic = original_monotonic

        self.assertEqual(first_cooldown, scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0])
        self.assertEqual(second_cooldown, scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0] * 2)
        self.assertEqual(backoff.slow_limit_level, 2)

    def test_fast_requests_reduce_slow_limit_level_after_recovery(self):
        backoff = scraper.RequestBackoff(persist=False)
        backoff.slow_limit_level = 2

        for _index in range(scraper.SLOW_LIMIT_FAST_RECOVERY_COUNT):
            backoff.note_fast_request(1)

        self.assertEqual(backoff.slow_limit_level, 1)
        self.assertEqual(backoff.fast_request_count, 0)

    def test_backoff_can_skip_regular_spacing_but_keep_cooldown(self):
        original_sleep = scraper.time.sleep
        original_monotonic = scraper.time.monotonic
        sleeps = []
        now = [1000]
        try:
            scraper.time.sleep = lambda seconds: sleeps.append(seconds)
            scraper.time.monotonic = lambda: now[0]
            backoff = scraper.RequestBackoff(persist=False)
            backoff.next_request_at = now[0] + 30

            waited = backoff.wait(include_spacing=False)
        finally:
            scraper.time.sleep = original_sleep
            scraper.time.monotonic = original_monotonic

        self.assertEqual(waited, 0)
        self.assertEqual(sleeps, [])

    def test_backoff_skip_spacing_still_waits_for_blocked_until(self):
        original_sleep = scraper.time.sleep
        original_monotonic = scraper.time.monotonic
        sleeps = []
        now = [1000]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        try:
            scraper.time.sleep = fake_sleep
            scraper.time.monotonic = lambda: now[0]
            backoff = scraper.RequestBackoff(persist=False)
            backoff.blocked_until = now[0] + 12
            backoff.next_request_at = now[0] + 30

            waited = backoff.wait(include_spacing=False)
        finally:
            scraper.time.sleep = original_sleep
            scraper.time.monotonic = original_monotonic

        self.assertEqual(round(waited), 12)
        self.assertEqual([round(value) for value in sleeps], [12])

    def test_backoff_spacing_factor_scales_regular_interval(self):
        original_uniform = scraper.random.uniform
        original_monotonic = scraper.time.monotonic
        try:
            scraper.random.uniform = lambda start, _end: start
            scraper.time.monotonic = lambda: 1000
            backoff = scraper.RequestBackoff(min_interval=1.0, interval_jitter=(0.2, 0.4), persist=False)

            waited = backoff.wait(spacing_factor=0.5)
        finally:
            scraper.random.uniform = original_uniform
            scraper.time.monotonic = original_monotonic

        self.assertEqual(waited, 0)
        self.assertAlmostEqual(backoff.next_request_at, 1000.6)

    def test_backoff_persists_blocked_until_for_new_instance(self):
        original_time = scraper.time.time
        original_monotonic = scraper.time.monotonic
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                state_path = Path(tmpdir) / "backoff.json"
                scraper.time.time = lambda: 1000
                scraper.time.monotonic = lambda: 500

                first = scraper.RequestBackoff(state_path=state_path)
                first.block_for(120)

                scraper.time.time = lambda: 1030
                scraper.time.monotonic = lambda: 700
                second = scraper.RequestBackoff(state_path=state_path)
                remaining = round(second.blocked_until - scraper.time.monotonic())
        finally:
            scraper.time.time = original_time
            scraper.time.monotonic = original_monotonic

        self.assertEqual(remaining, 90)

    def test_backoff_persists_slow_limit_level_for_restarted_worker(self):
        original_uniform = scraper.random.uniform
        original_time = scraper.time.time
        original_monotonic = scraper.time.monotonic
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                state_path = Path(tmpdir) / "backoff.json"
                scraper.random.uniform = lambda start, _end: start
                wall_now = [1000]
                mono_now = [500]
                scraper.time.time = lambda: wall_now[0]
                scraper.time.monotonic = lambda: mono_now[0]

                first = scraper.RequestBackoff(state_path=state_path)
                first.note_slow_request(120)
                wall_now[0] += 100
                mono_now[0] += 100
                first.note_slow_request(120)
                wall_now[0] += 100
                mono_now[0] += 100
                first.note_slow_request(120)

                wall_now[0] += scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0] + 60
                mono_now[0] += scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0] + 60
                second = scraper.RequestBackoff(state_path=state_path)
                cooldown = second.note_slow_request(120)
        finally:
            scraper.random.uniform = original_uniform
            scraper.time.time = original_time
            scraper.time.monotonic = original_monotonic

        self.assertEqual(second.slow_limit_level, 2)
        self.assertEqual(cooldown, scraper.SLOW_LIMIT_COOLDOWN_SECONDS[0] * 2)

    def test_warmup_skips_transient_network_failure(self):
        class FailingOpener:
            def open(self, _req, timeout=30):
                raise TimeoutError("timed out")

        client = scraper.BilibiliClient(scraper.make_headers(BVID, ""), use_proxy=False)
        client.opener = FailingOpener()
        logs = []

        client.warmup(BVID, logger=logs.append)

        self.assertTrue(any("warmup skipped" in item for item in logs))

    def test_ipv4_first_dns_prefers_ipv4_results(self):
        original_getaddrinfo = scraper.socket.getaddrinfo
        original_original_getaddrinfo = scraper.ORIGINAL_GETADDRINFO
        original_installed = scraper.IPV4_FIRST_DNS_INSTALLED

        def fake_getaddrinfo(*_args, **_kwargs):
            return [
                (socket.AF_INET6, None, None, "", ("2409::1", 443, 0, 0)),
                (socket.AF_INET, None, None, "", ("1.2.3.4", 443)),
            ]

        try:
            scraper.socket.getaddrinfo = fake_getaddrinfo
            scraper.ORIGINAL_GETADDRINFO = fake_getaddrinfo
            scraper.IPV4_FIRST_DNS_INSTALLED = False
            scraper.install_ipv4_first_dns()

            infos = scraper.socket.getaddrinfo("api.bilibili.com", 443)
        finally:
            scraper.socket.getaddrinfo = original_getaddrinfo
            scraper.ORIGINAL_GETADDRINFO = original_original_getaddrinfo
            scraper.IPV4_FIRST_DNS_INSTALLED = original_installed

        self.assertEqual(infos[0][0], socket.AF_INET)

    def test_wbi_mixin_key_cache_reuses_recent_key(self):
        calls = []

        class FakeClient:
            def request_json(self, _url, **_kwargs):
                calls.append(_url)
                return {
                    "code": 0,
                    "data": {
                        "isLogin": True,
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/" + ("a" * 64) + ".png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/" + ("b" * 64) + ".png",
                        },
                    },
                }

        original_time = scraper.time.time
        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(Path(tmpdir) / "wbi.json")
                scraper.time.time = lambda: 1000
                scraper.WBI_MIXIN_KEY_CACHE["value"] = None
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
                first = scraper.get_wbi_mixin_key(FakeClient(), lambda _message: None)
                second = scraper.get_wbi_mixin_key(FakeClient(), lambda _message: None)
        finally:
            scraper.time.time = original_time
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_wbi_mixin_key_force_refresh_bypasses_cache(self):
        calls = []

        class FakeClient:
            def request_json(self, _url, **_kwargs):
                calls.append(_url)
                return {
                    "code": 0,
                    "data": {
                        "isLogin": True,
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/" + ("c" * 64) + ".png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/" + ("d" * 64) + ".png",
                        },
                    },
                }

        original_time = scraper.time.time
        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(Path(tmpdir) / "wbi.json")
                scraper.time.time = lambda: 1000
                scraper.WBI_MIXIN_KEY_CACHE["value"] = "cached-key"
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 2000
                value = scraper.get_wbi_mixin_key(FakeClient(), lambda _message: None, force_refresh=True)
        finally:
            scraper.time.time = original_time
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

        self.assertNotEqual(value, "cached-key")
        self.assertEqual(len(calls), 1)

    def test_wbi_mixin_key_fetch_does_not_wait_for_global_backoff(self):
        kwargs_seen = []

        class FakeClient:
            def request_json(self, _url, **kwargs):
                kwargs_seen.append(kwargs)
                return {
                    "code": 0,
                    "data": {
                        "isLogin": True,
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/" + ("f" * 64) + ".png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/" + ("0" * 64) + ".png",
                        },
                    },
                }

        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(Path(tmpdir) / "wbi.json")
                scraper.WBI_MIXIN_KEY_CACHE["value"] = None
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
                scraper.get_wbi_mixin_key(FakeClient(), lambda _message: None, force_refresh=True)
        finally:
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

        self.assertEqual(kwargs_seen[0]["wait_for_backoff"], False)

    def test_wbi_mixin_key_uses_persisted_key_when_nav_is_unavailable(self):
        class FailingClient:
            def request_json(self, _url, **_kwargs):
                raise TimeoutError("nav timed out")

        original_time = scraper.time.time
        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        original_fallback = scraper.fetch_wbi_nav_with_system_opener
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cache_path = Path(tmpdir) / "wbi.json"
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(cache_path)
                scraper.time.time = lambda: 1000
                scraper.WBI_MIXIN_KEY_CACHE["value"] = None
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
                scraper.persist_wbi_mixin_key("e" * 32, expires_at=2000)
                scraper.fetch_wbi_nav_with_system_opener = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    TimeoutError("fallback timed out")
                )
                logs = []

                value = scraper.get_wbi_mixin_key(FailingClient(), logs.append, force_refresh=True)
        finally:
            scraper.time.time = original_time
            scraper.fetch_wbi_nav_with_system_opener = original_fallback
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

        self.assertEqual(value, "e" * 32)
        self.assertTrue(any("reused persisted WBI" in item for item in logs))

    def test_wbi_mixin_key_raises_specific_error_without_cache(self):
        class FailingClient:
            def request_json(self, _url, **_kwargs):
                raise TimeoutError("nav timed out")

        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        original_fallback = scraper.fetch_wbi_nav_with_system_opener
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(Path(tmpdir) / "wbi.json")
                scraper.WBI_MIXIN_KEY_CACHE["value"] = None
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
                scraper.fetch_wbi_nav_with_system_opener = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    TimeoutError("fallback timed out")
                )

                with self.assertRaises(scraper.WbiSignatureUnavailableError):
                    scraper.get_wbi_mixin_key(FailingClient(), lambda _message: None, force_refresh=True)
        finally:
            scraper.fetch_wbi_nav_with_system_opener = original_fallback
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

    def test_wbi_mixin_key_uses_system_opener_fallback(self):
        class FailingClient:
            headers = {"Cookie": "SESSDATA=secret", "User-Agent": "test-agent"}

            def request_json(self, _url, **_kwargs):
                raise TimeoutError("direct nav timed out")

        def fallback(headers, **_kwargs):
            fallback_headers.append(headers)
            return {
                "code": 0,
                "data": {
                    "isLogin": False,
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/" + ("1" * 64) + ".png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/" + ("2" * 64) + ".png",
                    },
                },
            }

        fallback_headers = []
        logs = []
        original_env = os.environ.get(scraper.WBI_CACHE_PATH_ENV)
        original_fallback = scraper.fetch_wbi_nav_with_system_opener
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = str(Path(tmpdir) / "wbi.json")
                scraper.WBI_MIXIN_KEY_CACHE["value"] = None
                scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
                scraper.fetch_wbi_nav_with_system_opener = fallback

                value = scraper.get_wbi_mixin_key(FailingClient(), logs.append, force_refresh=True)
        finally:
            scraper.fetch_wbi_nav_with_system_opener = original_fallback
            scraper.WBI_MIXIN_KEY_CACHE["value"] = None
            scraper.WBI_MIXIN_KEY_CACHE["expires_at"] = 0
            if original_env is None:
                os.environ.pop(scraper.WBI_CACHE_PATH_ENV, None)
            else:
                os.environ[scraper.WBI_CACHE_PATH_ENV] = original_env

        self.assertEqual(len(value), 32)
        self.assertEqual(fallback_headers[0]["Cookie"], "SESSDATA=secret")
        self.assertTrue(any("system opener fallback" in item for item in logs))

    def test_call_with_hard_timeout_raises_timeout(self):
        original_thread = scraper.threading.Thread
        original_queue = scraper.queue.Queue

        class NeverStartedThread:
            def __init__(self, target=None, daemon=None):
                self.target = target
                self.daemon = daemon

            def start(self):
                return None

        class AlwaysEmptyQueue:
            def __init__(self, maxsize=0):
                self.maxsize = maxsize

            def put(self, _value):
                return None

            def get(self, timeout=None):
                raise scraper.queue.Empty()

        try:
            scraper.threading.Thread = NeverStartedThread
            scraper.queue.Queue = AlwaysEmptyQueue
            with self.assertRaises(TimeoutError):
                scraper.call_with_hard_timeout(lambda: "ok", 0.01, "too slow")
        finally:
            scraper.threading.Thread = original_thread
            scraper.queue.Queue = original_queue

    def test_child_fetch_is_skipped_when_main_reply_already_has_all_children(self):
        class FailingClient:
            def request_json(self, _url, **_kwargs):
                raise AssertionError("child API should not be called when embedded replies are complete")

        child_reply = {
            "rpid_str": "2",
            "oid_str": "123",
            "type": 1,
            "mid_str": "100",
            "root_str": "1",
            "parent_str": "1",
            "dialog_str": "0",
            "ctime": 1700000001,
            "like": 1,
            "rcount": 0,
            "count": 0,
            "state": 0,
            "attr": 0,
            "content": {"message": "embedded child"},
            "member": {"mid": "100", "uname": "user-100"},
        }
        main_reply = {
            "rpid_str": "1",
            "oid_str": "123",
            "type": 1,
            "mid_str": "42",
            "root_str": "0",
            "parent_str": "0",
            "dialog_str": "0",
            "ctime": 1700000000,
            "like": 8,
            "rcount": 1,
            "count": 1,
            "state": 0,
            "attr": 0,
            "content": {"message": "parent"},
            "member": {"mid": "42", "uname": "owner"},
            "replies": [child_reply],
        }
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            comments, comment_items, summary = scraper.build_threaded_output(
                [main_reply],
                "123",
                FailingClient(),
                0.35,
                lambda _message: None,
            )
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comment_items), 2)
        self.assertEqual(summary[0]["fetched_count"], 1)
        self.assertEqual(sleeps, [])

    def test_child_fetch_blocked_request_raises_without_internal_retries(self):
        calls = []
        logs = []

        class BlockedClient:
            backoff = scraper.RequestBackoff(persist=False)

            def request_json(self, url, **kwargs):
                calls.append((url, kwargs))
                raise scraper.BilibiliRequestError("blocked", status=412, url=url)

        with self.assertRaises(scraper.BilibiliRequestError):
            scraper.fetch_child_replies("123", "456", 10, BlockedClient(), 0, logs.append)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["retries"], 1)
        self.assertTrue(any("blocked by HTTP 412" in item for item in logs))
        self.assertGreater(BlockedClient.backoff.blocked_until, 0)

    def test_main_reply_fetch_can_stop_after_page_limit(self):
        calls = []

        class FakeClient:
            def request_json(self, url, **_kwargs):
                calls.append(url)
                return {
                    "code": 0,
                    "data": {
                        "replies": [
                            {
                                "rpid_str": str(len(calls)),
                                "oid_str": "123",
                                "type": 1,
                                "mid_str": "42",
                                "root_str": "0",
                                "parent_str": "0",
                                "dialog_str": "0",
                                "ctime": 1700000000 + len(calls),
                                "content": {"message": "page"},
                                "member": {"mid": "42", "uname": "owner"},
                            }
                        ],
                        "cursor": {"all_count": 100, "next": len(calls), "is_end": False},
                    },
                }

        replies, api_count = scraper.fetch_main_replies(
            "123",
            FakeClient(),
            "1" * 32,
            0,
            lambda _message: None,
            max_pages=2,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(replies), 2)
        self.assertEqual(api_count, 100)

    def test_main_reply_fetch_treats_closed_comments_as_empty_archive(self):
        class ClosedCommentClient:
            def request_json(self, url, **_kwargs):
                raise scraper.BilibiliRequestError(
                    "API code=12061 message=UP主已关闭评论区",
                    api_code=12061,
                    api_message="UP主已关闭评论区",
                    url=url,
                )

        logs = []
        replies, api_count = scraper.fetch_main_replies(
            "123",
            ClosedCommentClient(),
            "1" * 32,
            0,
            logs.append,
        )

        self.assertEqual(replies, [])
        self.assertEqual(api_count, 0)
        self.assertTrue(any("comments closed" in item for item in logs))

    def test_child_fetch_can_be_skipped_for_fast_archive(self):
        class FailingClient:
            def clone(self):
                raise AssertionError("child API should not be called in fast archive mode")

        main_reply = {
            "rpid_str": "1",
            "oid_str": "123",
            "type": 1,
            "mid_str": "42",
            "root_str": "0",
            "parent_str": "0",
            "dialog_str": "0",
            "ctime": 1700000000,
            "like": 8,
            "rcount": 5,
            "count": 5,
            "state": 0,
            "attr": 0,
            "content": {"message": "parent"},
            "member": {"mid": "42", "uname": "owner"},
            "replies": [],
        }
        logs = []

        comments, comment_items, summary = scraper.build_threaded_output(
            [main_reply],
            "123",
            FailingClient(),
            0.35,
            logs.append,
            fetch_children=False,
        )

        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comment_items), 1)
        self.assertEqual(summary[0]["expected_rcount"], 5)
        self.assertEqual(summary[0]["fetched_count"], 0)
        self.assertTrue(any("skipping children fetch" in item for item in logs))

    def test_child_progress_updates_stage_stats_after_main_pages(self):
        main_stats = progress_stats(
            "comments",
            "main page 109: got=17 unique=2177 all_count=9791 next=2995 is_end=False",
            {},
        )
        child_stats = progress_stats(
            "comments",
            "fetching children 12/109 root=987654 expected=34",
            main_stats,
        )
        child_percent = progress_percent("comments", "fetching children 12/109 root=987654 expected=34", 65)

        self.assertEqual(child_stats["主评论页"], "109")
        self.assertEqual(child_stats["楼中楼进度"], "12 / 109")
        self.assertEqual(child_stats["当前根评论"], "987654")
        self.assertEqual(child_stats["当前楼中楼预期"], "34")
        self.assertGreater(child_percent, 65)

    def test_child_done_progress_reports_total_child_counts(self):
        stats = progress_stats(
            "comments",
            "children done 12/109 root=987654 fetched=2 total_fetched=341 total_expected=1518",
            {},
        )
        child_percent = progress_percent(
            "comments",
            "children done 12/109 root=987654 fetched=2 total_fetched=341 total_expected=1518",
            65,
        )

        self.assertEqual(stats["楼中楼进度"], "12 / 109")
        self.assertEqual(stats["当前根评论"], "987654")
        self.assertEqual(stats["当前楼中楼已抓"], "2")
        self.assertEqual(stats["楼中楼总已抓"], "341")
        self.assertEqual(stats["楼中楼预期总数"], "1518")
        self.assertGreater(child_percent, 65)


    def test_space_mid_can_be_extracted_from_url_or_plain_mid(self):
        self.assertEqual(extract_space_mid("https://space.bilibili.com/395188578/video"), "395188578")
        self.assertEqual(extract_space_mid("395188578"), "395188578")
        self.assertEqual(extract_space_mid("https://www.bilibili.com/video/BV1xx411c7mD"), "")

    def test_space_completion_accepts_zero_comment_video_when_api_count_is_zero(self):
        status = {
            "BV1closed": {"fetched_at": "2026-06-09T00:00:00+00:00", "api_comment_count": 0, "stat_reply": 0, "stat_danmaku": 7, "comments": 0, "danmaku": 12},
            "BV1empty": {"fetched_at": "2026-06-09T00:00:00+00:00", "api_comment_count": 0, "stat_reply": 0, "stat_danmaku": 0, "comments": 0, "danmaku": 0},
            "BV1partial": {"fetched_at": "2026-06-09T00:00:00+00:00", "api_comment_count": 10, "stat_reply": 10, "stat_danmaku": 7, "comments": 0, "danmaku": 12},
            "BV1missing_danmaku": {"fetched_at": "2026-06-09T00:00:00+00:00", "api_comment_count": 1, "stat_reply": 1, "stat_danmaku": 7, "comments": 1, "danmaku": 0},
            "BV1not_saved": {"api_comment_count": 0, "stat_reply": 0, "stat_danmaku": 0, "comments": 0, "danmaku": 0},
        }

        self.assertTrue(is_complete({"bvid": "BV1closed", "comment": 0, "video_review": 7}, status))
        self.assertTrue(is_complete({"bvid": "BV1empty", "comment": 0, "video_review": 0}, status))
        self.assertFalse(is_complete({"bvid": "BV1partial"}, status))
        self.assertFalse(is_complete({"bvid": "BV1missing_danmaku", "comment": 1, "video_review": 7}, status))
        self.assertFalse(is_complete({"bvid": "BV1not_saved", "comment": 0, "video_review": 0}, status))

    def test_space_completion_uses_space_list_expected_counts(self):
        status = {
            "BV1zero_danmaku": {
                "fetched_at": "2026-06-09T00:00:00+00:00",
                "api_comment_count": 1,
                "stat_reply": 1,
                "stat_danmaku": None,
                "comments": 1,
                "danmaku": 0,
            },
            "BV1zero_all": {
                "fetched_at": "2026-06-09T00:00:00+00:00",
                "api_comment_count": None,
                "stat_reply": None,
                "stat_danmaku": None,
                "comments": 0,
                "danmaku": 0,
            },
        }

        self.assertTrue(is_complete({"bvid": "BV1zero_danmaku", "comment": 1, "video_review": 0}, status))
        self.assertTrue(is_complete({"bvid": "BV1zero_all", "comment": 0, "video_review": 0}, status))

    def test_space_progress_reports_video_totals(self):
        stats = progress_stats(
            "space",
            "UP视频失败 3/178 complete=24 archived=2 skipped=1 failed=1 bvid=BV1xx411c7mD",
            {},
        )
        percent = progress_percent(
            "space",
            "UP视频失败 3/178 complete=24 archived=2 skipped=1 failed=1 bvid=BV1xx411c7mD",
            5,
        )

        self.assertEqual(stats["UP视频进度"], "3 / 178")
        self.assertEqual(stats["UP视频总数"], "178")
        self.assertEqual(stats["已完成视频"], "24")
        self.assertEqual(stats["本次新增"], "2")
        self.assertEqual(stats["跳过视频"], "1")
        self.assertEqual(stats["失败视频"], "1")
        self.assertEqual(stats["当前视频"], "BV1xx411c7mD")
        self.assertGreater(percent, 5)

    def test_space_list_ready_does_not_finish_progress(self):
        percent = progress_percent(
            "space",
            "UP视频列表完成 total=10 complete=0 archived=0 skipped=0",
            5,
        )

        self.assertEqual(percent, 5)


    def test_wbi_unavailable_aborts_space_archive_with_clear_error(self):
        exc = scraper.WbiSignatureUnavailableError("WBI signature key is temporarily unavailable")
        payload, status = api_error_response(exc)

        self.assertTrue(should_abort_space_archive(exc))
        self.assertEqual(status, 502)
        self.assertIn("WBI", payload["error"])
        self.assertIn("暂停", payload["error"])


class LoggingTests(unittest.TestCase):
    def test_clean_fields_removes_sensitive_values_and_truncates_long_strings(self):
        cleaned = clean_fields(
            {
                "token": "secret",
                "nested": {"cookie": "hidden", "safe": "visible"},
                "items": list(range(60)),
                "message": "x" * 600,
            }
        )
        self.assertNotIn("token", cleaned)
        self.assertEqual(cleaned["nested"], {"safe": "visible"})
        self.assertEqual(len(cleaned["items"]), 50)
        self.assertTrue(cleaned["message"].endswith("...[truncated]"))

    def test_bounded_queue_drops_low_priority_and_keeps_warning_when_full(self):
        log_queue = queue.Queue(maxsize=1)
        handler = BoundedQueueHandler(log_queue)
        first = logging.LogRecord("test", logging.INFO, __file__, 1, "first", (), None)
        second = logging.LogRecord("test", logging.INFO, __file__, 2, "second", (), None)
        warning = logging.LogRecord("test", logging.WARNING, __file__, 3, "warning", (), None)

        handler.emit(first)
        handler.emit(second)
        handler.emit(warning)

        self.assertEqual(log_queue.qsize(), 1)
        self.assertEqual(log_queue.get_nowait().getMessage(), "warning")


class TaskQueueTests(unittest.TestCase):
    def test_in_memory_queue_runs_tasks_and_records_history(self):
        events = []
        first_started = threading.Event()
        release_first = threading.Event()

        def runner(task):
            events.append(task["mid"])
            if task["mid"] == "1":
                first_started.set()
                release_first.wait(1)
            queue.update(task, status="finished", message="done", finished_at="done", progress=100)

        queue = InMemoryTaskQueue("space", runner, history_limit=2)
        first = queue.enqueue({"mid": "1", "owner_ref": "1"})
        self.assertTrue(first_started.wait(1))
        second = queue.enqueue({"mid": "2", "owner_ref": "2"})

        self.assertEqual(first["queue_position"], 1)
        self.assertEqual(second["queue_position"], 1)

        snapshot = queue.snapshot()
        self.assertEqual(snapshot["active"]["mid"], "1")
        self.assertEqual([task["mid"] for task in snapshot["queued"]], ["2"])
        release_first.set()

        deadline = time.time() + 2
        while time.time() < deadline:
            snapshot = queue.snapshot()
            if len(snapshot["recent"]) == 2:
                break
            time.sleep(0.01)

        snapshot = queue.snapshot()
        self.assertEqual(events, ["1", "2"])
        self.assertIsNone(snapshot["active"])
        self.assertEqual(snapshot["queued"], [])
        self.assertEqual([task["mid"] for task in snapshot["recent"]], ["2", "1"])
        self.assertEqual(snapshot["recent"][0]["failed"], 0)

    def test_in_memory_queue_marks_failures_and_continues(self):
        events = []

        def runner(task):
            events.append(task["mid"])
            if task["mid"] == "1":
                raise RuntimeError("boom")
            queue.update(task, status="finished", message="done", finished_at="done", progress=100)

        queue = InMemoryTaskQueue("space", runner, history_limit=3)
        queue.enqueue({"mid": "1", "owner_ref": "1"})
        queue.enqueue({"mid": "2", "owner_ref": "2"})

        deadline = time.time() + 2
        while time.time() < deadline:
            snapshot = queue.snapshot()
            if len(snapshot["recent"]) == 2:
                break
            time.sleep(0.01)

        snapshot = queue.snapshot()
        self.assertEqual(events, ["1", "2"])
        self.assertEqual([task["status"] for task in snapshot["recent"]], ["finished", "failed"])
        self.assertEqual(snapshot["recent"][1]["message"], "boom")
        self.assertEqual(snapshot["recent"][1]["failed"], 0)


class RequestParsingTests(unittest.TestCase):
    def test_control_capabilities_describe_machine_callable_actions(self):
        payload = control_capabilities()

        self.assertEqual(payload["version"], "v1")
        self.assertEqual(payload["namespace"], "/api/v1/control")
        self.assertEqual(payload["actions"]["videos.parse"]["endpoint"], "/api/v1/control/videos/parse")
        self.assertEqual(payload["actions"]["archive.export"]["endpoint"], "/api/v1/control/archive/export")
        self.assertIn("format=sqlite|json", payload["actions"]["archive.export"]["params"])

    def test_control_action_payload_normalizes_params(self):
        action, params = normalize_control_action_payload(
            {"action": "archive.export", "params": {"format": "json", "bvid": BVID}}
        )

        self.assertEqual(action, "archive.export")
        self.assertEqual(params["format"], "json")
        self.assertEqual(params["bvid"], BVID)

    def test_control_action_payload_rejects_unknown_action(self):
        with self.assertRaises(LookupError):
            normalize_control_action_payload({"action": "unknown.action", "params": {}})

    def test_parse_json_object_body_accepts_empty_or_object(self):
        self.assertEqual(parse_json_object_body(b""), {})
        self.assertEqual(parse_json_object_body(b"  "), {})
        self.assertEqual(parse_json_object_body(b'{"mid":"42"}'), {"mid": "42"})

    def test_parse_json_object_body_rejects_invalid_or_non_object_json(self):
        with self.assertRaises(BadRequestError):
            parse_json_object_body(b"{")
        with self.assertRaises(BadRequestError):
            parse_json_object_body(b"[]")
        with self.assertRaises(BadRequestError):
            parse_json_object_body("{}".encode("utf-16"))


if __name__ == "__main__":
    unittest.main()
