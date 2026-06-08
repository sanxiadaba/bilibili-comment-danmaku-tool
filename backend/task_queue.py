import threading
from datetime import datetime, timezone


DEFAULT_HISTORY_LIMIT = 10


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class InMemoryTaskQueue:
    def __init__(self, kind, runner, history_limit=DEFAULT_HISTORY_LIMIT):
        self.kind = kind
        self.runner = runner
        self.history_limit = history_limit
        self.condition = threading.Condition()
        self.queued = []
        self.active = None
        self.history = []
        self.worker_running = False
        self.next_id = 0

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
                **fields,
            }
            self.queued.append(task)
            queue_position = len(self.queued)
            if not self.worker_running:
                self.worker_running = True
                threading.Thread(target=self._worker_loop, daemon=True).start()
            self.condition.notify_all()
            return self.public_task(task, queue_position)

    def _worker_loop(self):
        while True:
            with self.condition:
                if not self.queued:
                    self.worker_running = False
                    return
                task = self.queued.pop(0)
                self.active = task
                self.update_locked(task, status="waiting", message="waiting for active task")

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
                self.condition.notify_all()

    def update(self, task, **fields):
        with self.condition:
            self.update_locked(task, **fields)
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
        }
        if queue_position is not None:
            payload["queue_position"] = queue_position
        return payload
