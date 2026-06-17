import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TEST_BACKEND = ROOT / "tests" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(TEST_BACKEND) not in sys.path:
    sys.path.insert(0, str(TEST_BACKEND))

from helpers import BVID, make_archive, make_comment

from bilibili_comment_danmaku.storage import load_comment_data, save_comments_to_sqlite, save_danmaku_to_sqlite
from database_registry import video_database_path_from_archive
from space_archive import SpaceArchiveService, database_dir_for_task, db_status_for_bvid, is_complete
from video_tasks import VideoParseTaskService


def danmaku_payload(bvid=BVID, count=1):
    return {
        "bvid": bvid,
        "cid": "456",
        "items": [
            {
                "bvid": bvid,
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
            for index in range(count)
        ],
    }


class TaskDatabaseLayoutTests(unittest.TestCase):
    def test_video_parse_task_saves_to_owner_bvid_database_and_updates_task_path(self):
        archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            task = {
                "id": "parse-1",
                "video_ref": BVID,
                "bvid": BVID,
                "database_dir": str(database_dir),
                "delay": 0,
                "request_id": "test",
            }
            service = VideoParseTaskService(Path(tmp) / "cookie.txt", threading.Lock(), state_path=None)
            with patch("video_tasks.scrape_comments", return_value=archive), patch(
                "video_tasks.scrape_danmaku", return_value=danmaku_payload()
            ), patch("video_tasks.inspect_cookie_status", return_value={"exists": True, "is_login": True}), patch(
                "video_tasks.start_progress"
            ), patch(
                "video_tasks.update_progress"
            ), patch(
                "video_tasks.finish_progress"
            ), patch(
                "video_tasks.fail_progress"
            ):
                service.run_parse_task(task)

            db_path = Path(task["db_path"])
            loaded = load_comment_data(db_path, bvid=BVID)

        self.assertEqual(db_path.name, f"{BVID}.db")
        self.assertEqual(db_path.parent.name, "Owner_42")
        self.assertEqual(task["status"], "finished")
        self.assertEqual(task["archived"], 1)
        self.assertEqual(loaded["metadata"]["bvid"], BVID)

    def test_space_archive_task_uses_existing_single_video_db_to_skip_complete_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)
            save_danmaku_to_sqlite(danmaku_payload(count=1), db_path, replace=True)
            task = {
                "id": "space-1",
                "mid": "42",
                "owner_ref": "42",
                "database_dir": str(database_dir),
                "options": {"delay": 0, "between_videos_min": 0, "between_videos_max": 0, "max_videos": 1, "no_cache": True},
            }
            service = SpaceArchiveService(Path(tmp) / "cookie.txt", Path(tmp) / "cache", threading.Lock(), state_path=None)
            item = {"bvid": BVID, "comment": 1, "video_review": 1}

            with patch("space_archive.inspect_cookie_status", return_value={"exists": True, "is_login": True}), patch(
                "space_archive.fetch_space_videos", return_value=[item]
            ), patch("space_archive.scrape_comments") as scrape_comments, patch("space_archive.scrape_danmaku") as scrape_danmaku, patch(
                "space_archive.update_progress"
            ), patch(
                "space_archive.start_progress"
            ), patch(
                "space_archive.finish_progress"
            ), patch(
                "space_archive.fail_progress"
            ):
                service.run_archive_task(task)

        self.assertEqual(task["status"], "finished")
        self.assertEqual(task["skipped"], 1)
        self.assertEqual(task["archived"], 0)
        scrape_comments.assert_not_called()
        scrape_danmaku.assert_not_called()

    def test_space_archive_task_saves_each_new_video_to_owner_folder(self):
        archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            task = {
                "id": "space-1",
                "mid": "42",
                "owner_ref": "42",
                "database_dir": str(database_dir),
                "options": {"delay": 0, "between_videos_min": 0, "between_videos_max": 0, "max_videos": 1, "no_cache": True},
            }
            service = SpaceArchiveService(Path(tmp) / "cookie.txt", Path(tmp) / "cache", threading.Lock(), state_path=None)

            with patch("space_archive.inspect_cookie_status", return_value={"exists": True, "is_login": True}), patch(
                "space_archive.fetch_space_videos", return_value=[{"bvid": BVID, "comment": 1, "video_review": 1}]
            ), patch("space_archive.scrape_comments", return_value=archive), patch(
                "space_archive.scrape_danmaku", return_value=danmaku_payload()
            ), patch(
                "space_archive.random.uniform", return_value=0
            ), patch(
                "space_archive.time.sleep"
            ), patch(
                "space_archive.update_progress"
            ), patch(
                "space_archive.start_progress"
            ), patch(
                "space_archive.finish_progress"
            ), patch(
                "space_archive.fail_progress"
            ):
                service.run_archive_task(task)
            expected_db = database_dir.resolve() / "Owner_42" / f"{BVID}.db"
            db_exists = expected_db.exists()
            loaded_total = load_comment_data(expected_db, bvid=BVID)["metadata"]["comment_total_count"] if db_exists else 0

        self.assertEqual(task["status"], "finished")
        self.assertEqual(task["archived"], 1)
        self.assertTrue(db_exists)
        self.assertEqual(loaded_total, 1)

    def test_space_status_checks_one_bvid_database_not_owner_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            archive = make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "hello")])
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)
            save_danmaku_to_sqlite(danmaku_payload(count=1), db_path, replace=True)

            status = db_status_for_bvid(db_path, BVID)

        self.assertTrue(is_complete({"bvid": BVID, "comment": 1, "video_review": 1}, status))
        self.assertFalse(is_complete({"bvid": "BVmissing1111", "comment": 1, "video_review": 1}, status))

    def test_database_dir_for_legacy_task_migrates_parent_to_databases_subdir(self):
        self.assertEqual(database_dir_for_task({"database_dir": "D:/app/data/databases"}), Path("D:/app/data/databases"))
        self.assertEqual(database_dir_for_task({"db_path": "D:/app/data/comment_danmaku.db"}), Path("D:/app/data/databases"))
        self.assertEqual(database_dir_for_task({"db_path": "D:/app/data/databases"}), Path("D:/app/data/databases"))


if __name__ == "__main__":
    unittest.main()
