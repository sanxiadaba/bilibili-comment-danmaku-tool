"""删除任务：按视频或 UP 主删除本地档案，分批提交并汇报进度。"""

from datetime import datetime, timezone
import time

from app_logging import log_event, log_exception
from bilibili_comment_danmaku import delete_owner_from_sqlite, delete_videos_from_sqlite
from progress_state import fail_progress, finish_progress, start_progress, update_progress
from space_archive import TaskCancelled
from task_queue import InMemoryTaskQueue

PAUSE_POLL_SECONDS = 0.2


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ArchiveDeleteTaskService:
    def __init__(self, refresh_lock, state_path=None, vacuum_scheduler=None):
        self.refresh_lock = refresh_lock
        self.vacuum_scheduler = vacuum_scheduler
        self.queue = InMemoryTaskQueue("delete", self.run_queue_task, state_path=state_path, retry_validator=self.can_retry_task)

    def enqueue(self, db_path, owner_mid="", bvids=None, request_id=""):
        selected_bvids = [str(item).strip() for item in (bvids or []) if str(item).strip()]
        owner_mid = str(owner_mid or "").strip()
        fields = {
            "request_id": request_id,
            "db_path": str(db_path),
            "owner_ref": f"UP {owner_mid}" if owner_mid else "视频删除",
            "target_kind": "owner" if owner_mid else "video",
            "owner_mid": owner_mid,
            "bvids": selected_bvids,
            "bvid": selected_bvids[0] if len(selected_bvids) == 1 else "",
            "total": len(selected_bvids),
            "message": "删除任务已加入队列",
        }
        return self.queue.enqueue(fields)

    def snapshot(self):
        return self.queue.snapshot()

    def start_pending_tasks(self):
        self.queue.start_pending_worker()

    def control_tasks(self, action, task_id=None, retry_defaults=None):
        return self.queue.control(action, task_id=task_id, retry_defaults=retry_defaults or {})

    def can_retry_task(self, task):
        return bool(task.get("db_path") and (task.get("owner_mid") or task.get("bvids")))

    def progress_target(self, task):
        return str(task.get("bvid") or task.get("owner_ref") or task.get("id") or "")

    def run_queue_task(self, task):
        if task.get("stop_requested"):
            self.queue.update(
                task,
                status="stopped",
                message="删除任务已停止",
                finished_at=utc_now(),
                pause_requested=False,
                stop_requested=False,
            )
            return

        self.queue.update(
            task,
            status="waiting",
            started_at=utc_now(),
            message="等待当前数据库任务完成",
            progress=3,
        )
        self.refresh_lock.acquire()
        try:
            if task.get("stop_requested"):
                self.queue.update(
                    task,
                    status="stopped",
                    message="删除任务已停止",
                    finished_at=utc_now(),
                    pause_requested=False,
                    stop_requested=False,
                )
                return
            self.queue.update(task, status="running", message="正在删除本地档案", progress=12)
            start_progress("delete", self.progress_target(task), "正在删除本地档案")
            self.run_delete_task(task)
        finally:
            self.refresh_lock.release()

    def run_delete_task(self, task):
        db_path = task["db_path"]
        owner_mid = str(task.get("owner_mid") or "").strip()
        bvids = [str(item).strip() for item in (task.get("bvids") or []) if str(item).strip()]
        request_id = task.get("request_id", "")
        try:
            log_event(
                "task.archive_delete.start",
                "archive delete task started",
                request_id=request_id,
                task_id=task["id"],
                db=str(db_path),
                owner_mid=owner_mid,
                bvid_count=len(bvids),
            )
            self.queue.update(task, message="正在删除评论、弹幕和视频记录", progress=35)
            update_progress("delete", self.progress_target(task), "正在删除评论、弹幕和视频记录")
            progress = self.delete_progress_callback(task)
            result = (
                delete_owner_from_sqlite(db_path, owner_mid, vacuum=False, progress_callback=progress)
                if owner_mid
                else delete_videos_from_sqlite(db_path, bvids, vacuum=False, progress_callback=progress)
            )
            deleted_videos = result.get("deleted_videos", 0)
            deleted_bvids = result.get("deleted_bvids") or []
            counts = result.get("counts") or {}
            message = f"已删除 {deleted_videos} 个视频"
            self.queue.update(
                task,
                status="finished",
                message=message,
                finished_at=utc_now(),
                total=deleted_videos or len(bvids),
                complete=deleted_videos,
                archived=deleted_videos,
                skipped=0,
                failed=0,
                progress=100,
                current_bvid=deleted_bvids[0] if len(deleted_bvids) == 1 else "",
                pause_requested=False,
                stop_requested=False,
            )
            finish_progress("delete", self.progress_target(task), message)
            log_event(
                "task.archive_delete.finish",
                "archive delete task finished",
                request_id=request_id,
                task_id=task["id"],
                db=str(db_path),
                owner_mid=owner_mid,
                deleted_videos=deleted_videos,
                counts=counts,
                bytes_reclaimed=result.get("bytes_reclaimed", 0),
                vacuum_deferred=result.get("vacuum_deferred"),
                wal_peak=result.get("wal_peak", 0),
                wal_after=result.get("wal_after", 0),
                chunks=result.get("chunks", 0),
            )
            if self.vacuum_scheduler:
                self.vacuum_scheduler(db_path, request_id)
        except TaskCancelled:
            message = "删除任务已停止，已删除的部分可重新发起删除完成"
            self.queue.update(
                task,
                status="stopped",
                message=message,
                finished_at=utc_now(),
                pause_requested=False,
                stop_requested=False,
            )
            finish_progress("delete", self.progress_target(task), message)
            log_event(
                "task.archive_delete.cancelled",
                "archive delete task stopped by user",
                request_id=request_id,
                task_id=task.get("id", ""),
                db=str(db_path),
                owner_mid=owner_mid,
            )
        except LookupError as exc:
            # The previous attempt already committed the last batch (or another path removed
            # the rows), so nothing is left to delete: that is success, not a failure.
            # Retrying a finished delete used to land here and be reported as failed.
            message = "目标已不存在，删除视为已完成"
            target_total = len(bvids) or (1 if owner_mid else 0)
            self.queue.update(
                task,
                status="finished",
                message=message,
                finished_at=utc_now(),
                total=target_total,
                complete=0,
                archived=0,
                skipped=target_total,
                failed=0,
                progress=100,
                pause_requested=False,
                stop_requested=False,
            )
            finish_progress("delete", self.progress_target(task), message)
            log_event(
                "task.archive_delete.already_gone",
                "delete target no longer exists; treated as finished",
                request_id=request_id,
                task_id=task.get("id", ""),
                db=str(db_path),
                owner_mid=owner_mid,
                bvid_count=len(bvids),
                reason=str(exc),
                level="warning",
            )
        except Exception as exc:
            self.queue.update(
                task,
                status="failed",
                message=str(exc),
                finished_at=utc_now(),
                failed=1,
                pause_requested=False,
                stop_requested=False,
            )
            fail_progress("delete", self.progress_target(task), str(exc))
            log_exception(
                "task.archive_delete.error",
                str(exc),
                request_id=request_id,
                task_id=task.get("id", ""),
                db=str(db_path),
                owner_mid=owner_mid,
                bvid_count=len(bvids),
            )

    def delete_progress_callback(self, task):
        labels = {
            "comments": "正在分批删除评论",
            "danmaku": "正在分批删除弹幕",
            "videos": "正在删除视频记录",
        }

        def progress(payload):
            self.wait_while_paused(task)
            if task.get("stop_requested"):
                raise TaskCancelled("stop")
            stage = payload.get("stage", "delete")
            chunks = int(payload.get("chunks") or 0)
            wal_peak = int(payload.get("wal_peak") or 0)
            wal_after = int(payload.get("wal_after") or 0)
            message = f"{labels.get(stage, '正在删除')}，已处理 {chunks} 批，WAL 峰值 {format_bytes(wal_peak)}，当前 {format_bytes(wal_after)}"
            self.queue.update(
                task,
                message=message,
                progress=min(92, 35 + chunks),
            )
            update_progress("delete", self.progress_target(task), message)

        return progress

    def wait_while_paused(self, task):
        """Pause between delete batches until the user resumes or stops.

        Deleting is destructive, so unlike archiving it never resumes itself after a
        timeout: a forgotten pause keeps waiting (the user can still resume or stop).
        """
        if not task.get("pause_requested"):
            return
        self.queue.update(task, status="paused", message="删除任务已暂停，等待继续")
        while task.get("pause_requested") and not task.get("stop_requested"):
            time.sleep(PAUSE_POLL_SECONDS)
        if not task.get("stop_requested"):
            self.queue.update(task, status="running", message="正在删除本地档案")


def format_bytes(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        size = 0.0
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
