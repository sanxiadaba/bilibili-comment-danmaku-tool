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

    def test_queue_persists_and_recovers_pending_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "queue.json"
            first_started = threading.Event()
            release_first = threading.Event()

            def blocked_runner(task):
                first_started.set()
                release_first.wait(1)
                queue.update(task, status="finished", message="done", finished_at="done", progress=100)

            queue = InMemoryTaskQueue("space", blocked_runner, state_path=state_path)
            queue.enqueue({"mid": "1", "owner_ref": "1", "db_path": "D:/data/comment_danmaku.db"})
            self.assertTrue(first_started.wait(1))
            queue.enqueue({"mid": "2", "owner_ref": "2", "db_path": "D:/data/comment_danmaku.db"})

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["active"]["mid"], "1")
            self.assertEqual([task["mid"] for task in persisted["queued"]], ["2"])

            recovered = InMemoryTaskQueue("space", lambda task: None, state_path=state_path)
            snapshot = recovered.snapshot()
            self.assertIsNone(snapshot["active"])
            self.assertEqual([task["mid"] for task in snapshot["queued"]], ["1", "2"])
            self.assertEqual([task["status"] for task in snapshot["queued"]], ["queued", "queued"])

            release_first.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if len(queue.snapshot()["recent"]) == 2:
                    break
                time.sleep(0.01)

    def test_queue_starts_recovered_tasks_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "queue.json"
            state_path.write_text(
                json.dumps(
                    {
                        "kind": "space",
                        "next_id": 2,
                        "active": {
                            "id": "space-1",
                            "kind": "space",
                            "mid": "1",
                            "owner_ref": "1",
                            "status": "running",
                            "message": "interrupted",
                            "created_at": "2024-01-01T00:00:00+00:00",
                            "updated_at": "2024-01-01T00:00:01+00:00",
                            "started_at": "2024-01-01T00:00:01+00:00",
                            "finished_at": "",
                            "progress": 50,
                            "current_bvid": "BV1",
                            "total": 2,
                            "complete": 1,
                            "archived": 1,
                            "skipped": 0,
                            "failed": 0,
                        },
                        "queued": [
                            {
                                "id": "space-2",
                                "kind": "space",
                                "mid": "2",
                                "owner_ref": "2",
                                "status": "queued",
                                "message": "queued",
                                "created_at": "2024-01-01T00:00:00+00:00",
                                "updated_at": "2024-01-01T00:00:00+00:00",
                                "started_at": "",
                                "finished_at": "",
                                "progress": 0,
                                "current_bvid": "",
                                "total": 0,
                                "complete": 0,
                                "archived": 0,
                                "skipped": 0,
                                "failed": 0,
                            }
                        ],
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )
            events = []

            def runner(task):
                events.append(task["mid"])
                queue.update(task, status="finished", message="done", finished_at="done", progress=100)

            queue = InMemoryTaskQueue("space", runner, history_limit=3, state_path=state_path)
            queue.start_pending_worker()

            deadline = time.time() + 2
            while time.time() < deadline:
                snapshot = queue.snapshot()
                if len(snapshot["recent"]) == 2:
                    break
                time.sleep(0.01)

            snapshot = queue.snapshot()
            self.assertEqual(events, ["1", "2"])
            self.assertEqual(snapshot["queued"], [])
            self.assertEqual([task["mid"] for task in snapshot["recent"]], ["2", "1"])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIsNone(persisted["active"])
            self.assertEqual(persisted["queued"], [])
            self.assertEqual([task["mid"] for task in persisted["history"]], ["2", "1"])

    def test_queue_can_pause_resume_and_stop_queued_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "queue.json"
            events = []
            release = threading.Event()

            def runner(task):
                events.append(task["mid"])
                release.wait(1)
                queue.update(task, status="finished", message="done", finished_at="done", progress=100)

            queue = InMemoryTaskQueue("space", runner, state_path=state_path)
            first = queue.enqueue({"mid": "1", "owner_ref": "1"})
            second = queue.enqueue({"mid": "2", "owner_ref": "2"})
            paused = queue.control("pause", task_id=second["id"])
            self.assertEqual(paused["queue"]["queued"][0]["status"], "paused")

            resumed = queue.control("resume", task_id=second["id"])
            self.assertEqual(resumed["queue"]["queued"][0]["status"], "queued")
            self.assertFalse(resumed["queue"]["queued"][0]["pause_requested"])

            stopped = queue.control("stop", task_id=second["id"])
            self.assertEqual(stopped["queue"]["queued"], [])
            self.assertEqual(stopped["changed"][0]["status"], "stopped")
            self.assertEqual(queue.snapshot()["recent"][0]["status"], "stopped")

            release.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if len(queue.snapshot()["recent"]) == 2:
                    break
                time.sleep(0.01)

            self.assertEqual(events, ["1"])

    def test_queue_pause_and_stop_active_are_visible_to_runner(self):
        active_started = threading.Event()
        release_active = threading.Event()
        observed = []

        def runner(task):
            active_started.set()
            release_active.wait(1)
            observed.append((task.get("pause_requested"), task.get("stop_requested")))
            queue.update(task, status="finished", message="done", finished_at="done", progress=100)

        queue = InMemoryTaskQueue("space", runner)
        first = queue.enqueue({"mid": "1", "owner_ref": "1"})
        self.assertTrue(active_started.wait(1))
        pause_result = queue.control("pause", task_id=first["id"])
        stop_result = queue.control("stop", task_id=first["id"])
        self.assertTrue(pause_result["changed"][0]["pause_requested"])
        self.assertTrue(stop_result["changed"][0]["stop_requested"])
        release_active.set()

        deadline = time.time() + 2
        while time.time() < deadline:
            if observed:
                break
            time.sleep(0.01)
        self.assertEqual(observed, [(True, True)])

    def test_combined_queue_keeps_waiting_parse_task_visible(self):
        import server

        original_space = server.space_archive_service
        original_video = server.video_parse_service

        class FakeService:
            def __init__(self, snapshot):
                self._snapshot = snapshot

            def snapshot(self):
                return self._snapshot

        try:
            server.space_archive_service = FakeService(
                {
                    "active": {
                        "id": "space-1",
                        "kind": "space",
                        "status": "running",
                        "updated_at": "2026-06-13T00:00:02+00:00",
                    },
                    "queued": [],
                    "recent": [],
                }
            )
            server.video_parse_service = FakeService(
                {
                    "active": {
                        "id": "parse-1",
                        "kind": "parse",
                        "status": "waiting",
                        "bvid": "BV1xx411c7mD",
                        "updated_at": "2026-06-13T00:00:01+00:00",
                    },
                    "queued": [],
                    "recent": [],
                }
            )

            snapshot = server.combined_queue_snapshot()

            self.assertEqual(snapshot["active"]["id"], "space-1")
            self.assertEqual(snapshot["queued"][0]["id"], "parse-1")
            self.assertEqual(snapshot["queued"][0]["queue_position"], 1)
        finally:
            server.space_archive_service = original_space
            server.video_parse_service = original_video

    def test_active_task_returning_paused_goes_back_to_queue(self):
        active_started = threading.Event()
        release_active = threading.Event()

        def runner(task):
            active_started.set()
            release_active.wait(1)
            queue.update(task, status="paused", message="paused", progress=25)

        queue = InMemoryTaskQueue("space", runner)
        first = queue.enqueue({"mid": "1", "owner_ref": "1"})
        self.assertTrue(active_started.wait(1))
        queue.control("pause", task_id=first["id"])
        release_active.set()

        deadline = time.time() + 2
        while time.time() < deadline:
            snapshot = queue.snapshot()
            if snapshot["queued"] and snapshot["queued"][0]["status"] == "paused":
                break
            time.sleep(0.01)

        snapshot = queue.snapshot()
        self.assertIsNone(snapshot["active"])
        self.assertEqual(snapshot["queued"][0]["id"], first["id"])
        self.assertEqual(snapshot["queued"][0]["status"], "paused")
        self.assertEqual(snapshot["recent"], [])



