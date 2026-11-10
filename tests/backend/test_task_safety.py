import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive, make_comment

import task_queue as task_queue_module  # noqa: E402
from archive_delete_tasks import ArchiveDeleteTaskService  # noqa: E402
from bilibili_comment_danmaku import load_danmaku_data, save_comments_to_sqlite, save_danmaku_to_sqlite  # noqa: E402
from space_archive import TaskCancelled, is_complete, meets_expected  # noqa: E402
from task_queue import InMemoryTaskQueue  # noqa: E402


def danmaku_payload(count=1, like_counts=None):
    items = []
    for index in range(count):
        like = None if like_counts is None else like_counts
        items.append(
            {
                "bvid": BVID,
                "cid": "456",
                "dmid": str(1000 + index),
                "progress": 1.0 + index,
                "mode": 1,
                "font_size": 25,
                "color": 0xFFFFFF,
                "ctime": 1700000000 + index,
                "pool": 0,
                "user_hash": f"hash-{index}",
                "weight": 9,
                "like_count": like,
                "content": f"danmaku {index}",
                "fetched_at": "2024-01-01T00:00:00+00:00",
            }
        )
    return {"bvid": BVID, "cid": "456", "items": items}


class CompletenessTests(unittest.TestCase):
    def test_meets_expected_uses_a_tolerance(self):
        self.assertTrue(meets_expected(0, 0))
        self.assertTrue(meets_expected(1, 1))
        self.assertTrue(meets_expected(900, 1000))
        self.assertFalse(meets_expected(899, 1000))
        self.assertFalse(meets_expected(20, 1000))
        self.assertFalse(meets_expected("bad", 10))

    def test_partial_archive_is_not_marked_complete(self):
        status = {
            BVID: {
                "fetched_at": "2024-01-01T00:00:00+00:00",
                "comments": 20,
                "danmaku": 100,
                "stat_reply": 1000,
                "stat_danmaku": 100,
                "api_comment_count": 1000,
            }
        }

        self.assertFalse(is_complete({"bvid": BVID, "comment": 1000, "video_review": 100}, status))
        status[BVID]["comments"] = 950
        self.assertTrue(is_complete({"bvid": BVID, "comment": 1000, "video_review": 100}, status))


class DanmakuLikePreservationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "archive.db"
        save_comments_to_sqlite(
            make_archive("2024-01-01T00:00:00+00:00", [make_comment("1", 1, "top", mid="42")]),
            self.db_path,
            replace=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _stored_like(self, dmid):
        payload = load_danmaku_data(self.db_path, bvid=BVID, limit=None)
        return next(item["like_count"] for item in payload["items"] if item["dmid"] == dmid)

    def test_missing_like_counts_do_not_wipe_stored_values(self):
        save_danmaku_to_sqlite(danmaku_payload(like_counts=12), self.db_path, replace=True)

        save_danmaku_to_sqlite(danmaku_payload(like_counts=None), self.db_path, replace=True)

        self.assertEqual(self._stored_like("1000"), 12)

    def test_known_zero_overwrites_stored_value(self):
        save_danmaku_to_sqlite(danmaku_payload(like_counts=12), self.db_path, replace=True)

        save_danmaku_to_sqlite(danmaku_payload(like_counts=0), self.db_path, replace=True)

        self.assertEqual(self._stored_like("1000"), 0)

    def test_replace_drops_danmaku_missing_from_the_new_scrape(self):
        save_danmaku_to_sqlite(danmaku_payload(3, like_counts=5), self.db_path, replace=True)

        save_danmaku_to_sqlite(danmaku_payload(1, like_counts=5), self.db_path, replace=True)

        payload = load_danmaku_data(self.db_path, bvid=BVID, limit=None)
        self.assertEqual([item["dmid"] for item in payload["items"]], ["1000"])


class TaskQueueStateTests(unittest.TestCase):
    def test_paused_task_stays_paused_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "space_queue.json"
            state_path.write_text(
                json.dumps(
                    {
                        "kind": "space",
                        "next_id": 1,
                        "active": None,
                        "queued": [
                            {
                                "id": "space-1",
                                "kind": "space",
                                "status": "paused",
                                "pause_requested": True,
                                "db_path": "D:/data/comment_danmaku.db",
                                "mid": "42",
                                "options": {"max_videos": 5},
                            }
                        ],
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )

            queue = InMemoryTaskQueue("space", lambda task: None, state_path=state_path)

            queued = queue.snapshot()["queued"]
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["status"], "paused")
            self.assertTrue(queued[0]["pause_requested"])

    def test_queued_task_still_resumes_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "space_queue.json"
            state_path.write_text(
                json.dumps(
                    {
                        "kind": "space",
                        "next_id": 1,
                        "queued": [{"id": "space-1", "kind": "space", "status": "queued", "mid": "42"}],
                    }
                ),
                encoding="utf-8",
            )

            queue = InMemoryTaskQueue("space", lambda task: None, state_path=state_path)

            self.assertEqual(queue.snapshot()["queued"][0]["status"], "queued")

    def test_corrupt_pointer_types_do_not_break_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "space_queue.json"
            state_path.write_text(
                json.dumps({"kind": "space", "next_id": "not-a-number", "queued": {}, "history": {}}),
                encoding="utf-8",
            )

            queue = InMemoryTaskQueue("space", lambda task: None, state_path=state_path)

            self.assertEqual(queue.next_id, 0)
            self.assertEqual(queue.snapshot()["queued"], [])

    def test_persist_failures_are_logged_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "space_queue.json"
            queue = InMemoryTaskQueue("space", lambda task: None, state_path=state_path)

            with mock.patch.object(task_queue_module, "log_event") as log_event, mock.patch(
                "pathlib.Path.replace", side_effect=PermissionError("locked")
            ):
                queue.persist_locked()
                queue.persist_locked()

            log_event.assert_called_once()
            self.assertEqual(log_event.call_args.args[0], "task_queue.persist_error")


class DeleteTaskControlTests(unittest.TestCase):
    def _service(self, tmp):
        return ArchiveDeleteTaskService(__import__("threading").Lock(), state_path=Path(tmp) / "delete_queue.json")

    def test_stop_request_aborts_between_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = {"id": "delete-1", "stop_requested": True}
            progress = service.delete_progress_callback(task)

            with self.assertRaises(TaskCancelled):
                progress({"stage": "comments", "chunks": 1, "wal_peak": 0, "wal_after": 0})

    def test_pause_request_blocks_until_resumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = {"id": "delete-1", "pause_requested": True}
            progress = service.delete_progress_callback(task)

            import threading
            import time

            timer = threading.Timer(0.5, lambda: task.update(pause_requested=False))
            timer.start()
            started_at = time.time()
            progress({"stage": "comments", "chunks": 1, "wal_peak": 0, "wal_after": 0})
            elapsed = time.time() - started_at
            timer.join(timeout=2)

            self.assertGreater(elapsed, 0.3)


if __name__ == "__main__":
    unittest.main()
