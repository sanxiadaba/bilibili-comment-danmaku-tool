import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_HISTORY_LIMIT = 10


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class InMemoryTaskQueue:
    def __init__(self, kind, runner, history_limit=DEFAULT_HISTORY_LIMIT, state_path=None):
        self.kind = kind
        self.runner = runner
        self.history_limit = history_limit
        self.state_path = Path(state_path) if state_path else None
        self.condition = threading.Condition()
        self.queued = []
        self.active = None
        self.history = []
        self.worker_running = False
        self.next_id = 0
        self.load_state()

    def enqueue(self, fields):
        now = utc_now()
        with self.condition:
            self.next_id += 1
            task = {
                "id": f"{self.kind}-{self.next_id}",
                "kind": self.kind,
                "status": "queued",
                "message": "queued",
                "created_at": now,
                "updated_at": now,
                "started_at": "",
                "finished_at": "",
                "progress": 0,
                "current_bvid": "",
                "total": 0,
                "complete": 0,
                "archived": 0,
                "skipped": 0,
                "failed": 0,
                **fields,
            }
            self.queued.append(task)
            queue_position = len(self.queued)
            self.persist_locked()
            self.start_worker_locked()
            self.condition.notify_all()
            return self.public_task(task, queue_position)

    def start_pending_worker(self):
        with self.condition:
            if self.queued:
                self.start_worker_locked()
                self.condition.notify_all()

    def start_worker_locked(self):
        if not self.worker_running:
            self.worker_running = True
            threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        while True:
            with self.condition:
                if not self.queued:
                    self.worker_running = False
                    self.persist_locked()
                    return
                task = self.queued.pop(0)
                self.active = task
                self.update_locked(task, status="waiting", message="waiting for active task")
                self.persist_locked()

            try:
                self.runner(task)
            except Exception as exc:
                self.update(
                    task,
                    status="failed",
                    message=str(exc),
                    finished_at=utc_now(),
                )

            with self.condition:
                if not task.get("finished_at"):
                    self.update_locked(
                        task,
                        status="finished",
                        message="finished",
                        finished_at=utc_now(),
                    )
                self.history.insert(0, self.public_task(task))
                del self.history[self.history_limit :]
                self.active = None
                self.persist_locked()
                self.condition.notify_all()

    def update(self, task, **fields):
        with self.condition:
            self.update_locked(task, **fields)
            self.persist_locked()
            self.condition.notify_all()

    def update_locked(self, task, **fields):
        task.update(fields)
        task["updated_at"] = utc_now()

    def snapshot(self):
        with self.condition:
            queued = [self.public_task(task, index + 1) for index, task in enumerate(self.queued)]
            return {
                "active": self.public_task(self.active) if self.active else None,
                "queued": queued,
                "recent": list(self.history),
            }

    def public_task(self, task, queue_position=None):
        payload = {
            "id": task.get("id", ""),
            "kind": task.get("kind", self.kind),
            "mid": task.get("mid", ""),
            "owner_ref": task.get("owner_ref", ""),
            "status": task.get("status", ""),
            "message": task.get("message", ""),
            "created_at": task.get("created_at", ""),
            "updated_at": task.get("updated_at", ""),
            "started_at": task.get("started_at", ""),
            "finished_at": task.get("finished_at", ""),
            "progress": task.get("progress", 0),
            "current_bvid": task.get("current_bvid", ""),
            "total": task.get("total", 0),
            "complete": task.get("complete", 0),
            "archived": task.get("archived", 0),
            "skipped": task.get("skipped", 0),
            "failed": task.get("failed", 0),
        }
        if queue_position is not None:
            payload["queue_position"] = queue_position
        return payload

    def load_state(self):
        if not self.state_path or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if payload.get("kind") and payload.get("kind") != self.kind:
            return

        self.next_id = int(payload.get("next_id") or 0)
        self.history = [
            task
            for task in payload.get("history", [])
            if isinstance(task, dict) and task.get("status") in {"finished", "failed"}
        ][: self.history_limit]

        recovered = []
        for task in payload.get("queued", []):
            if isinstance(task, dict):
                recovered.append(self.recover_pending_task(task))
        active = payload.get("active")
        if isinstance(active, dict):
            recovered.insert(0, self.recover_pending_task(active))
        self.queued = recovered

        max_id = self.next_id
        for task in [*self.queued, *self.history]:
            task_id = str(task.get("id") or "")
            prefix = f"{self.kind}-"
            if task_id.startswith(prefix):
                try:
                    max_id = max(max_id, int(task_id[len(prefix) :]))
                except ValueError:
                    pass
        self.next_id = max_id

    def recover_pending_task(self, task):
        now = utc_now()
        recovered = dict(task)
        recovered.update(
            {
                "kind": recovered.get("kind", self.kind),
                "status": "queued",
                "message": "service restarted; queued to resume",
                "updated_at": now,
                "started_at": "",
                "finished_at": "",
            }
        )
        return recovered

    def persist_locked(self):
        if not self.state_path:
            return
        payload = {
            "kind": self.kind,
            "next_id": self.next_id,
            "active": dict(self.active) if self.active else None,
            "queued": [dict(task) for task in self.queued],
            "history": list(self.history[: self.history_limit]),
            "updated_at": utc_now(),
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.state_path)
        except OSError:
            pass
