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

from archive_delete_tasks import ArchiveDeleteTaskService  # noqa: E402
from app_logging import BoundedQueueHandler, clean_fields  # noqa: E402
from control_api import control_capabilities, control_openapi_document, normalize_control_action_payload  # noqa: E402
from database_registry import (  # noqa: E402
    export_database_path,
    import_database_file,
    list_database_catalog,
    parse_multipart_files,
    resolve_database_path,
)
from errors import BadRequestError  # noqa: E402
from progress_state import progress_percent, progress_stats  # noqa: E402
from http_utils import parse_json_object_body  # noqa: E402
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
    delete_owner_from_sqlite,
    delete_videos_from_sqlite,
    load_comment_data,
    load_danmaku_data,
    list_video_summaries_page,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
    vacuum_database,
)
import bilibili_comment_danmaku.storage as storage  # noqa: E402
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
            summaries = list_video_summaries_page(db_path, limit=10)["videos"]

            self.assertEqual(loaded["metadata"]["total_count"], 2)
            self.assertEqual(loaded["metadata"]["limit"], 1)
            self.assertEqual(len(loaded["items"]), 1)
            self.assertTrue(loaded["items"][0]["is_up_owner"])
            self.assertEqual([bucket["bucket_start"] for bucket in loaded["buckets"]], [0, 10])
            self.assertEqual(summaries[0]["danmaku_count"], 2)

    def test_list_video_summaries_page_limits_aggregation_to_requested_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            archives = [
                ("BV1111111111", "2024-01-01T00:00:00+00:00", 1),
                ("BV2222222222", "2024-01-02T00:00:00+00:00", 2),
                ("BV3333333333", "2024-01-03T00:00:00+00:00", 3),
            ]

            for bvid, fetched_at, comment_count in archives:
                comments = [
                    make_comment(f"{bvid}-{index}", 1, f"comment {index}", like=index + 1)
                    for index in range(comment_count)
                ]
                archive = make_archive(fetched_at, comments)
                archive["metadata"]["bvid"] = bvid
                archive["metadata"]["source_url"] = f"https://www.bilibili.com/video/{bvid}"
                save_comments_to_sqlite(archive, db_path, replace=True)
                save_danmaku_to_sqlite(
                    {
                        "bvid": bvid,
                        "cid": "456",
                        "items": [
                            {
                                "bvid": bvid,
                                "cid": "456",
                                "dmid": f"{bvid}-dm-{index}",
                                "progress": float(index),
                                "mode": 1,
                                "font_size": 25,
                                "color": 0xFFFFFF,
                                "ctime": 1700000000 + index,
                                "pool": 0,
                                "user_hash": "hash",
                                "weight": 1,
                                "like_count": 0,
                                "content": f"danmaku {index}",
                                "fetched_at": fetched_at,
                            }
                            for index in range(comment_count)
                        ],
                    },
                    db_path,
                    replace=True,
                )

            page = list_video_summaries_page(db_path, limit=1, offset=1)

            self.assertEqual(page["total"], 3)
            self.assertEqual(page["limit"], 1)
            self.assertEqual(page["offset"], 1)
            self.assertTrue(page["has_more"])
            self.assertEqual([video["bvid"] for video in page["videos"]], ["BV2222222222"])
            self.assertEqual(page["videos"][0]["comment_total_count"], 2)
            self.assertEqual(page["videos"][0]["danmaku_count"], 2)

            fast_page = list_video_summaries_page(db_path, limit=1, offset=1, include_owners=False)
            self.assertNotIn("owners", fast_page)
            self.assertEqual([video["bvid"] for video in fast_page["videos"]], ["BV2222222222"])

    def test_video_page_owner_summaries_use_full_database_not_current_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            for index in range(3):
                archive = make_archive(f"2024-01-0{index + 1}T00:00:00+00:00", [make_comment(f"owner-{index}", 1, "comment")])
                archive["metadata"] = {
                    **archive["metadata"],
                    "bvid": f"BVowner{index:05d}",
                    "aid": 100 + index,
                    "source_url": f"https://www.bilibili.com/video/BVowner{index:05d}",
                }
                archive["video_raw"] = {**archive["video_raw"], "owner": {"mid": "42", "name": "Owner", "face": ""}}
                save_comments_to_sqlite(archive, db_path, replace=True)

            other = make_archive("2024-01-04T00:00:00+00:00", [make_comment("other", 1, "comment")])
            other["metadata"] = {**other["metadata"], "bvid": "BVother0001", "aid": 200, "source_url": "https://www.bilibili.com/video/BVother0001"}
            other["video_raw"] = {**other["video_raw"], "owner": {"mid": "100", "name": "Other", "face": ""}}
            save_comments_to_sqlite(other, db_path, replace=True)

            page = list_video_summaries_page(db_path, limit=1, offset=0)
            owners = {owner["owner_mid"]: owner for owner in page["owners"]}

            self.assertEqual(len(page["videos"]), 1)
            self.assertEqual(page["total"], 4)
            self.assertEqual(owners["42"]["video_count"], 3)
            self.assertEqual(owners["42"]["comment_count"], 3)
            self.assertEqual(owners["100"]["video_count"], 1)
            self.assertGreater(owners["42"]["storage_bytes"], owners["100"]["storage_bytes"])
            self.assertEqual(owners["42"]["key"], "mid:42")

    def test_delete_video_removes_related_archive_rows_and_keeps_other_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            first_top = make_comment("1", 1, "top comment", mid="42", like=8)
            second_top = make_comment("2", 1, "other comment", mid="100", like=3)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [first_top]), db_path, replace=True)
            second_archive = make_archive("2024-01-02T00:00:00+00:00", [second_top])
            second_archive["metadata"] = {
                **second_archive["metadata"],
                "bvid": "BV2222222222",
                "aid": 222,
                "source_url": "https://www.bilibili.com/video/BV2222222222",
            }
            second_archive["video_raw"] = {**second_archive["video_raw"], "owner": {"mid": "100", "name": "Other", "face": ""}}
            save_comments_to_sqlite(second_archive, db_path, replace=True)
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

            result = delete_videos_from_sqlite(db_path, [BVID], vacuum=False)
            page = list_video_summaries_page(db_path, limit=10)

            self.assertEqual(result["deleted_videos"], 1)
            self.assertTrue(result["vacuum_deferred"])
            self.assertEqual(result["deleted_bvids"], [BVID])
            self.assertEqual(result["counts"]["comments"], 1)
            self.assertEqual(result["counts"]["comment_pictures"], 1)
            self.assertEqual(result["counts"]["comment_emotes"], 1)
            self.assertEqual(result["counts"]["danmaku"], 1)
            self.assertEqual([video["bvid"] for video in page["videos"]], ["BV2222222222"])
            with self.assertRaises(LookupError):
                load_comment_data(db_path, bvid=BVID)

    def test_delete_video_uses_chunked_commits_to_limit_wal_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            comments = [make_comment(str(index), 1, f"comment {index}", mid=str(index)) for index in range(12)]
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", comments), db_path, replace=True)
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": f"dm-{index}",
                            "progress": float(index),
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000000 + index,
                            "pool": 0,
                            "user_hash": "hash",
                            "weight": 1,
                            "like_count": 0,
                            "content": f"danmaku {index}",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        }
                        for index in range(9)
                    ],
                },
                db_path,
                replace=True,
            )
            original_comment_batch = storage.DELETE_COMMENT_BATCH_SIZE
            original_danmaku_batch = storage.DELETE_DANMAKU_BATCH_SIZE
            original_threshold = storage.DEFAULT_WAL_CHECKPOINT_THRESHOLD_BYTES
            progress = []
            try:
                storage.DELETE_COMMENT_BATCH_SIZE = 5
                storage.DELETE_DANMAKU_BATCH_SIZE = 4
                storage.DEFAULT_WAL_CHECKPOINT_THRESHOLD_BYTES = 1
                result = delete_videos_from_sqlite(db_path, [BVID], vacuum=False, progress_callback=progress.append)
            finally:
                storage.DELETE_COMMENT_BATCH_SIZE = original_comment_batch
                storage.DELETE_DANMAKU_BATCH_SIZE = original_danmaku_batch
                storage.DEFAULT_WAL_CHECKPOINT_THRESHOLD_BYTES = original_threshold

            self.assertEqual(result["deleted_videos"], 1)
            self.assertGreater(result["chunks"], 1)
            self.assertGreaterEqual(result["wal_peak"], result["wal_after"])
            self.assertLess(result["wal_after"], 1024 * 1024)
            self.assertLess(result["wal_peak"], 1024 * 1024)
            self.assertEqual(storage.set_database_journal_mode(db_path, "WAL").lower(), "wal")
            self.assertGreaterEqual(len(progress), 3)
            self.assertEqual({item["stage"] for item in progress}, {"comments", "danmaku", "videos"})
            with self.assertRaises(LookupError):
                load_comment_data(db_path, bvid=BVID)

    def test_delete_owner_removes_all_owner_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)
            owner_second = make_archive("2024-01-02T00:00:00+00:00", [])
            owner_second["metadata"] = {
                **owner_second["metadata"],
                "bvid": "BV2222222222",
                "aid": 222,
                "source_url": "https://www.bilibili.com/video/BV2222222222",
            }
            save_comments_to_sqlite(owner_second, db_path, replace=True)
            other = make_archive("2024-01-03T00:00:00+00:00", [])
            other["metadata"] = {**other["metadata"], "bvid": "BV3333333333", "aid": 333, "source_url": "https://www.bilibili.com/video/BV3333333333"}
            other["video_raw"] = {**other["video_raw"], "owner": {"mid": "100", "name": "Other", "face": ""}}
            save_comments_to_sqlite(other, db_path, replace=True)

            result = delete_owner_from_sqlite(db_path, "42", vacuum=False)
            page = list_video_summaries_page(db_path, limit=10)

            self.assertEqual(result["deleted_videos"], 2)
            self.assertEqual(set(result["deleted_bvids"]), {BVID, "BV2222222222"})
            self.assertEqual([video["bvid"] for video in page["videos"]], ["BV3333333333"])

    def test_archive_delete_task_deletes_in_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), db_path, replace=True)
            scheduled = []
            service = ArchiveDeleteTaskService(threading.Lock(), vacuum_scheduler=lambda path, request_id="": scheduled.append((Path(path), request_id)))

            task = service.enqueue(db_path, bvids=[BVID], request_id="req-1")
            self.assertTrue(task["id"].startswith("delete-"))
            self.assertEqual(task["queue_position"], 1)
            self.assertTrue(service.queue.wait_until_idle(timeout=2))

            snapshot = service.snapshot()
            self.assertIsNone(snapshot["active"])
            self.assertEqual(snapshot["recent"][0]["status"], "finished")
            self.assertEqual(snapshot["recent"][0]["complete"], 1)
            self.assertEqual(scheduled, [(db_path, "req-1")])
            with self.assertRaises(LookupError):
                load_comment_data(db_path, bvid=BVID)

    def test_vacuum_database_reports_reclaimed_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)

            result = vacuum_database(db_path)

            self.assertIn("size_before", result)
            self.assertIn("size_after", result)
            self.assertGreaterEqual(result["bytes_reclaimed"], 0)

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
            summaries = list_video_summaries_page(export_path, limit=10)["videos"]
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
            summaries = list_video_summaries_page(export_path, limit=10)["videos"]

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

    def test_database_catalog_reports_storage_and_top_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            top = make_comment("1", 1, "top comment", mid="100", like=8)
            reply = make_comment("2", 2, "reply comment", root="1", parent="1", mid="101", like=3)
            top["replies"] = [reply]
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), main_db, replace=True)

            catalog = list_database_catalog(main_db, hotplug_dir)
            main = {item["id"]: item for item in catalog}["main"]

            self.assertGreater(main["page_count"], 0)
            self.assertGreater(main["page_size"], 0)
            self.assertGreaterEqual(main["used_bytes"], 0)
            self.assertGreaterEqual(main["reclaimable_bytes"], 0)
            self.assertIn("storage_message", main)
            self.assertEqual(main["top_owners"][0]["owner_mid"], "42")
            self.assertEqual(main["top_owners"][0]["video_count"], 1)
            self.assertEqual(main["top_owners"][0]["comment_count"], 2)

    def test_database_catalog_can_skip_expensive_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            hotplug_dir = root / "databases"
            top = make_comment("1", 1, "top comment", mid="100", like=8)
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), main_db, replace=True)

            catalog = list_database_catalog(main_db, hotplug_dir, include_details=False)
            main = {item["id"]: item for item in catalog}["main"]

            self.assertTrue(main["ok"])
            self.assertEqual(main["video_count"], 1)
            self.assertEqual(main["comment_count"], 1)
            self.assertEqual(main["top_owners"], [])
            self.assertEqual(main["coverage_status"], "unique")

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

    def test_export_database_path_uses_readable_label_before_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_path = export_database_path("UP_测试UP_42_8videos", Path(tmp), suffix=".db")

            self.assertTrue(export_path.name.startswith("UP_测试UP_42_8videos_"))
            self.assertTrue(export_path.name.endswith(".db"))

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
