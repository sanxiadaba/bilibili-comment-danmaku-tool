from datetime import datetime, timezone

from app_logging import log_event, log_exception
from bilibili_comment_danmaku import (
    extract_bvid,
    load_comment_data,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
    scrape_comments,
    scrape_danmaku,
)
from progress_state import fail_progress, finish_progress, make_progress_logger, parse_float, start_progress, update_progress
from space_archive import api_error_response
from space_archive import TaskCancelled
from task_queue import InMemoryTaskQueue


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class VideoParseTaskService:
    def __init__(self, cookie_file, refresh_lock, state_path=None):
        self.cookie_file = cookie_file
        self.refresh_lock = refresh_lock
        self.queue = InMemoryTaskQueue("parse", self.run_queue_task, state_path=state_path, retry_validator=self.can_retry_task)

    def enqueue(self, db_path, video_ref, delay, request_id=""):
        bvid = extract_bvid(video_ref)
        return self.queue.enqueue(
            {
                "mid": "",
                "owner_ref": "视频抓取",
                "request_id": request_id,
                "db_path": str(db_path),
                "video_ref": video_ref,
                "bvid": bvid,
                "delay": parse_float(delay, 0.35),
                "total": 1,
            }
        )

    def snapshot(self):
        return self.queue.snapshot()

    def start_pending_tasks(self):
        self.queue.start_pending_worker()

    def control_tasks(self, action, task_id=None, retry_defaults=None):
        defaults = {"cookie_file": str(self.cookie_file)}
        defaults.update(dict(retry_defaults or {}))
        return self.queue.control(
            action,
            task_id=task_id,
            retry_defaults=defaults,
        )

    def can_retry_task(self, task):
        return bool(task.get("db_path") and (task.get("video_ref") or task.get("bvid")))

    def run_queue_task(self, task):
        self.refresh_lock.acquire()
        try:
            self.queue.update(
                task,
                status="running",
                started_at=utc_now(),
                message="正在抓取视频",
                progress=5,
                current_bvid=task.get("bvid", ""),
            )
            self.run_parse_task(task)
        finally:
            self.refresh_lock.release()

    def stop_or_pause_requested(self, task, bvid, progress):
        if task.get("stop_requested"):
            self.queue.update(
                task,
                status="stopped",
                message="已停止",
                finished_at=utc_now(),
                current_bvid=bvid,
                progress=progress,
            )
            finish_progress("parse", bvid, "视频抓取已停止")
            return True
        if task.get("pause_requested"):
            self.queue.update(
                task,
                status="paused",
                message="已暂停，可继续",
                finished_at="",
                current_bvid=bvid,
                progress=progress,
            )
            update_progress("parse", bvid, "视频抓取已暂停")
            return True
        return False

    def cancellation_logger(self, task, bvid, logs, progress):
        base_log = make_progress_logger("parse", bvid, logs)

        def log(message):
            if task.get("stop_requested"):
                self.queue.update(
                    task,
                    status="stopped",
                    message="已停止",
                    finished_at=utc_now(),
                    current_bvid=bvid,
                    progress=progress,
                    pause_requested=False,
                    stop_requested=False,
                )
                finish_progress("parse", bvid, "视频抓取已停止")
                raise TaskCancelled("stop")
            if task.get("pause_requested"):
                self.queue.update(
                    task,
                    status="paused",
                    message="已暂停，可继续",
                    finished_at="",
                    current_bvid=bvid,
                    progress=progress,
                )
                update_progress("parse", bvid, "视频抓取已暂停")
                raise TaskCancelled("pause")
            base_log(message)

        return log

    def run_parse_task(self, task):
        db_path = task["db_path"]
        video_ref = task["video_ref"]
        bvid = task.get("bvid") or extract_bvid(video_ref)
        delay = task.get("delay", 0.35)
        request_id = task.get("request_id", "")
        logs = []
        try:
            try:
                before = load_comment_data(db_path, bvid=bvid)["metadata"]["comment_total_count"]
            except LookupError:
                before = 0

            log_event(
                "task.parse.start",
                "parse video task started",
                request_id=request_id,
                db=str(db_path),
                bvid=bvid,
                task_id=task["id"],
                delay=delay,
                existing_comment_count=before,
            )
            start_progress("parse", bvid, "准备解析视频并抓取评论")
            log = self.cancellation_logger(task, bvid, logs, 80)

            if self.stop_or_pause_requested(task, bvid, 5):
                return

            output_data = scrape_comments(
                video_ref,
                cookie_file=str(self.cookie_file),
                delay=delay,
                logger=log,
            )
            bvid = output_data["metadata"]["bvid"]
            task["bvid"] = bvid

            if self.stop_or_pause_requested(task, bvid, 80):
                return
            self.queue.update(task, current_bvid=bvid, message="正在保存评论", progress=82)
            update_progress("parse", bvid, "评论抓取完成，正在保存评论归档")
            save_comments_to_sqlite(output_data, db_path, replace=True)

            if self.stop_or_pause_requested(task, bvid, 86):
                return
            self.queue.update(task, current_bvid=bvid, message="正在抓取弹幕", progress=88)
            update_progress("parse", bvid, "正在抓取弹幕")
            danmaku_log = self.cancellation_logger(task, bvid, logs, 88)
            danmaku_result = scrape_danmaku(
                bvid,
                output_data["video_raw"],
                logger=danmaku_log,
            )
            if len(danmaku_result.get("items") or []) > 0:
                self.queue.update(task, message="正在保存弹幕", progress=94)
                update_progress("parse", bvid, "弹幕抓取完成，正在保存弹幕归档")
                save_danmaku_to_sqlite(danmaku_result, db_path, replace=True)
            else:
                log("danmaku: got=0, skipped saving empty danmaku archive")
                log_event(
                    "task.parse.empty_danmaku_skipped",
                    "parse skipped saving empty danmaku archive",
                    request_id=request_id,
                    bvid=bvid,
                )

            payload = load_comment_data(db_path, bvid=bvid)
            self.queue.update(
                task,
                status="finished",
                message="视频抓取完成",
                finished_at=utc_now(),
                current_bvid=bvid,
                complete=1,
                archived=1,
                failed=0,
                progress=100,
                pause_requested=False,
                stop_requested=False,
            )
            finish_progress("parse", bvid, "解析与抓取完成")
            log_event(
                "task.parse.finish",
                "parse video task finished",
                request_id=request_id,
                task_id=task["id"],
                bvid=bvid,
                before_count=before,
                scraped_count=output_data["metadata"]["comment_total_count"],
                after_count=payload["metadata"]["comment_total_count"],
                danmaku_count=len(danmaku_result.get("items") or []),
            )
        except Exception as exc:
            if isinstance(exc, TaskCancelled):
                return
            payload, status = api_error_response(exc)
            self.queue.update(
                task,
                status="failed",
                message=payload["error"],
                finished_at=utc_now(),
                current_bvid=bvid,
                failed=1,
                pause_requested=False,
                stop_requested=False,
            )
            fail_progress("parse", bvid, payload["error"])
            log_exception(
                "task.parse.error",
                payload["error"],
                request_id=request_id,
                task_id=task.get("id", ""),
                bvid=bvid,
                status=status,
            )
