import threading
import unittest
from pathlib import Path

from helpers import BVID

from server import task_retry_defaults  # noqa: E402
from task_queue import InMemoryTaskQueue  # noqa: E402

GOOD_DB = Path("D:/data/databases/Owner_42") / f"{BVID}.db"
LEGACY_DB = Path("D:/data/comment_danmaku.db")
ARCHIVE_OPTIONS = {
    "max_videos": 5,
    "no_cache": True,
    "delay": 1.5,
    "skip_danmaku": False,
    "skip_danmaku_likes": True,
}


def failed_task(**overrides):
    task = {
        "id": "space-1",
        "kind": "space",
        "status": "failed",
        "message": "抓取失败",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:10+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": "2026-01-01T00:00:10+00:00",
        "progress": 12,
        "current_bvid": BVID,
        "total": 5,
        "complete": 1,
        "archived": 1,
        "skipped": 0,
        "failed": 1,
        "mid": "42",
        "owner_ref": "42",
        "db_path": str(GOOD_DB),
        "database_dir": str(GOOD_DB.parent),
        "options": dict(ARCHIVE_OPTIONS),
        "cookie_file": "D:/data/cookie.txt",
    }
    task.update(overrides)
    return task


class RetryFieldsTests(unittest.TestCase):
    def test_retry_defaults_never_carry_a_target_database(self):
        defaults = task_retry_defaults(Path("D:/data/databases"))

        self.assertNotIn("db_path", defaults)
        self.assertNotIn("options", defaults)
        self.assertEqual(defaults["database_dir"], str(Path("D:/data/databases")))

    def test_retry_fields_keep_the_stored_target_database(self):
        queue = InMemoryTaskQueue("space", lambda task: None)
        task = failed_task()

        fields = queue.retry_fields(
            task,
            {"db_path": str(LEGACY_DB), "options": {"max_videos": 0}, "cookie_file": "D:/data/cookie.txt"},
        )

        self.assertEqual(fields["db_path"], str(GOOD_DB))
        self.assertEqual(fields["options"], ARCHIVE_OPTIONS)
        self.assertEqual(fields["database_dir"], str(GOOD_DB.parent))

    def test_retry_fields_only_fill_missing_keys(self):
        queue = InMemoryTaskQueue("space", lambda task: None)
        task = failed_task()
        task.pop("cookie_file")

        fields = queue.retry_fields(task, {"cookie_file": "D:/data/cookie.txt", "database_dir": "D:/other"})

        self.assertEqual(fields["cookie_file"], "D:/data/cookie.txt")
        self.assertEqual(fields["database_dir"], str(GOOD_DB.parent))

    def test_retry_fields_reset_runtime_flags(self):
        queue = InMemoryTaskQueue("space", lambda task: None)
        task = failed_task(pause_requested=True, stop_requested=True, queue_position=3)

        fields = queue.retry_fields(task, {})

        self.assertEqual(fields["retry_of"], "space-1")
        self.assertFalse(fields["pause_requested"])
        self.assertFalse(fields["stop_requested"])
        self.assertNotIn("status", fields)
        self.assertNotIn("queue_position", fields)
        self.assertNotIn("progress", fields)


class RetryReplayTests(unittest.TestCase):
    def test_replayed_task_keeps_the_original_database_and_options(self):
        seen = []
        finished = threading.Event()

        def runner(task):
            seen.append({"db_path": task.get("db_path"), "options": task.get("options")})
            queue.update(task, status="finished", message="done", finished_at="done")
            finished.set()

        queue = InMemoryTaskQueue(
            "space",
            runner,
            retry_validator=lambda task: bool(task.get("db_path") and task.get("mid")),
        )
        queue.history = [failed_task()]

        queue.control("retry", task_id="space-1", retry_defaults=task_retry_defaults(Path("D:/data/databases")))

        self.assertTrue(finished.wait(5))
        self.assertEqual(seen, [{"db_path": str(GOOD_DB), "options": ARCHIVE_OPTIONS}])

    def test_replayed_task_does_not_fall_back_to_the_legacy_database(self):
        seen = []
        finished = threading.Event()

        def runner(task):
            seen.append(task.get("db_path"))
            queue.update(task, status="finished", message="done", finished_at="done")
            finished.set()

        queue = InMemoryTaskQueue(
            "delete",
            runner,
            retry_validator=lambda task: bool(task.get("db_path") and task.get("bvids")),
        )
        queue.history = [
            failed_task(
                id="delete-1",
                kind="delete",
                owner_mid="",
                bvids=[BVID],
                options=None,
            )
        ]

        queue.control(
            "retry",
            task_id="delete-1",
            retry_defaults={"db_path": str(LEGACY_DB), "database_dir": str(GOOD_DB.parent)},
        )

        self.assertTrue(finished.wait(5))
        self.assertEqual(seen, [str(GOOD_DB)])


if __name__ == "__main__":
    unittest.main()
