import argparse
import json
import mimetypes
import random
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app_logging import configure_logging, logging_status, log_event, log_exception, new_request_id, shutdown_logging
from bilibili_comment_danmaku import (
    export_archive_to_sqlite,
    extract_bvid,
    list_video_summaries,
    load_comment_data,
    load_danmaku_data,
    prepare_database_path,
    save_danmaku_to_sqlite,
    save_comments_to_sqlite,
    scrape_comments,
    scrape_danmaku,
)
from bilibili_comment_danmaku import scraper
from bilibili_comment_danmaku.scraper import BilibiliRequestError
from bilibili_comment_danmaku.storage import connect, ensure_schema
from task_queue import InMemoryTaskQueue


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_STATIC = ROOT / "dist"
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_SPACE_CACHE_DIR = ROOT / "data" / "space_cache"
DEFAULT_DATABASE_DIR = ROOT / "data" / "databases"
LEGACY_EXPORT_DIR = ROOT / "data" / "exports"
DEFAULT_EXPORT_DIR = DEFAULT_DATABASE_DIR
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
refresh_lock = threading.Lock()
progress_lock = threading.Lock()
progress_state = {
    "active": False,
    "kind": "",
    "bvid": "",
    "message": "",
    "logs": [],
    "percent": 0,
    "stage": "",
    "stats": {},
    "started_at": "",
    "updated_at": "",
    "done": False,
    "error": "",
}


class BadRequestError(ValueError):
    pass


class CommentDanmakuServer(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB
    static_dir = DEFAULT_STATIC
    log_dir = DEFAULT_LOG_DIR
    database_dir = DEFAULT_DATABASE_DIR

    def do_GET(self):
        self.start_request_log("GET")
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/databases":
                self.handle_databases_api()
                return
            if parsed.path == "/api/videos":
                self.handle_videos_api()
                return
            if parsed.path == "/api/comments":
                self.handle_comments_api(parsed)
                return
            if parsed.path == "/api/danmaku":
                self.handle_danmaku_api(parsed)
                return
            if parsed.path == "/api/progress":
                self.handle_progress_api()
                return
            if parsed.path == "/api/refresh":
                self.handle_refresh_api(parsed)
                return
            if parsed.path == "/api/health":
                self.handle_health_api()
                return
            if parsed.path.startswith("/api/"):
                self.send_json({"error": f"未知 API：{parsed.path}"}, status=404)
                return
            self.handle_static(parsed.path)
        except Exception as exc:
            self.log_unhandled_exception(exc, parsed.path)
            raise
        finally:
            self.finish_request_log(parsed.path)

    def do_POST(self):
        self.start_request_log("POST")
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/videos/parse":
                self.handle_parse_video_api()
                return
            if parsed.path == "/api/space/archive":
                self.handle_space_archive_api()
                return
            if parsed.path == "/api/danmaku/refresh":
                self.handle_danmaku_refresh_api(parsed)
                return
            if parsed.path == "/api/refresh":
                self.handle_refresh_api(parsed)
                return
            if parsed.path == "/api/logs/client":
                self.handle_client_log_api()
                return
            if parsed.path == "/api/databases/import":
                self.handle_database_import_api()
                return
            if parsed.path == "/api/database/export":
                self.handle_database_export_api()
                return
            self.send_error(404)
        except BadRequestError as exc:
            log_event(
                "http.request.bad_request",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                method=getattr(self, "command", ""),
                path=parsed.path,
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self.log_unhandled_exception(exc, parsed.path)
            raise
        finally:
            self.finish_request_log(parsed.path)

    def start_request_log(self, method):
        self.request_id = new_request_id()
        self.request_started_at = time.perf_counter()
        self.response_status = 0
        parsed = urlparse(self.path)
        log_event(
            "http.request.start",
            f"{method} {parsed.path}",
            request_id=self.request_id,
            method=method,
            path=parsed.path,
            client=self.client_address[0] if self.client_address else "",
            user_agent=self.headers.get("User-Agent", ""),
        )

    def finish_request_log(self, path):
        duration_ms = int((time.perf_counter() - getattr(self, "request_started_at", time.perf_counter())) * 1000)
        log_event(
            "http.request.finish",
            f"{getattr(self, 'command', '')} {path} {getattr(self, 'response_status', 0)}",
            request_id=getattr(self, "request_id", ""),
            method=getattr(self, "command", ""),
            path=path,
            status=getattr(self, "response_status", 0),
            duration_ms=duration_ms,
        )

    def log_unhandled_exception(self, exc, path):
        log_exception(
            "http.request.unhandled_error",
            str(exc),
            request_id=getattr(self, "request_id", ""),
            method=getattr(self, "command", ""),
            path=path,
        )

    def handle_videos_api(self):
        db_path = self.resolve_db_path_from_query()
        try:
            videos = list_video_summaries(db_path)
            log_event(
                "api.videos.list",
                "listed local videos",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                video_count=len(videos),
            )
            self.send_json({"videos": videos, "database": database_info_for_path(db_path, self.db_path, self.database_dir)})
        except Exception as exc:
            log_exception("api.videos.list_error", str(exc), request_id=getattr(self, "request_id", ""))
            self.send_json({"error": str(exc)}, status=500)

    def handle_databases_api(self):
        databases = list_database_catalog(self.db_path, self.database_dir)
        log_event(
            "api.databases.list",
            "listed local databases",
            request_id=getattr(self, "request_id", ""),
            database_count=len(databases),
        )
        self.send_json(
            {
                "databases": databases,
                "active_id": parse_qs(urlparse(self.path).query).get("db_id", ["main"])[0] or "main",
                "hotplug_dir": str(self.database_dir),
                "legacy_export_dir": str(LEGACY_EXPORT_DIR),
            }
        )

    def handle_progress_api(self):
        self.send_json(get_progress_snapshot())

    def handle_health_api(self):
        logging = logging_status()
        log_event(
            "api.health",
            "health check",
            request_id=getattr(self, "request_id", ""),
            db=str(self.db_path),
            static_dir=str(self.static_dir),
            database_dir=str(self.database_dir),
            logging=logging,
        )
        self.send_json({"ok": True, "db": str(self.db_path), "database_dir": str(self.database_dir), "logging": logging})

    def handle_client_log_api(self):
        body = self.read_json_body()
        event = str(body.get("event") or "client.event")[:120]
        fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
        log_event(
            event if event.startswith("client.") else f"client.{event}",
            str(body.get("message") or event)[:300],
            request_id=getattr(self, "request_id", ""),
            page=str(body.get("page") or "")[:300],
            client_ts=str(body.get("ts") or "")[:80],
            fields=fields,
        )
        self.send_json({"ok": True})

    def handle_parse_video_api(self):
        if not refresh_lock.acquire(blocking=False):
            log_event(
                "task.rejected",
                "parse rejected because another task is active",
                request_id=getattr(self, "request_id", ""),
                kind="parse",
                reason="busy",
            )
            self.send_json({"error": "已有抓取任务正在进行，请稍后再试"}, status=409)
            return

        try:
            body = self.read_json_body()
            db_path = self.resolve_db_path_from_body(body)
            video_ref = (body.get("url") or body.get("video_ref") or body.get("bvid") or "").strip()
            if not video_ref:
                log_event(
                    "task.parse.invalid_input",
                    "parse request missing video reference",
                    request_id=getattr(self, "request_id", ""),
                    level="warning",
                )
                self.send_json({"error": "请输入 Bilibili 视频链接或 BV 号"}, status=400)
                return
            bvid = extract_bvid(video_ref)
            delay = parse_float(body.get("delay"), 0.35)
            try:
                before = load_comment_data(db_path, bvid=bvid)["metadata"]["comment_total_count"]
            except LookupError:
                before = 0

            log_event(
                "task.parse.start",
                "parse video started",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                bvid=bvid,
                delay=delay,
                existing_comment_count=before,
            )
            start_progress("parse", bvid, "准备解析视频并抓取评论")
            logs = []
            log = make_progress_logger("parse", bvid, logs)

            output_data = scrape_comments(
                video_ref,
                cookie_file=str(DEFAULT_COOKIE_FILE),
                delay=delay,
                logger=log,
            )
            update_progress("parse", bvid, "评论抓取完成，正在保存评论档案")
            save_comments_to_sqlite(output_data, db_path, replace=True)
            update_progress("parse", bvid, "正在抓取弹幕")
            danmaku_result = scrape_danmaku(
                output_data["metadata"]["bvid"],
                output_data["video_raw"],
                logger=log,
            )
            if len(danmaku_result.get("items") or []) > 0:
                update_progress("parse", bvid, "弹幕抓取完成，正在保存弹幕档案")
                save_danmaku_to_sqlite(danmaku_result, db_path, replace=True)
            else:
                log("danmaku: got=0, skipped saving empty danmaku archive")
                log_event(
                    "task.parse.empty_danmaku_skipped",
                    "parse skipped saving empty danmaku archive",
                    request_id=getattr(self, "request_id", ""),
                    bvid=bvid,
                )
            payload = load_comment_data(db_path, bvid=output_data["metadata"]["bvid"])
            finish_progress("parse", bvid, "解析与抓取完成")
            log_event(
                "task.parse.finish",
                "parse video finished",
                request_id=getattr(self, "request_id", ""),
                bvid=output_data["metadata"]["bvid"],
                before_count=before,
                scraped_count=output_data["metadata"]["comment_total_count"],
                after_count=payload["metadata"]["comment_total_count"],
                danmaku_count=len(danmaku_result.get("items") or []),
            )
            self.send_json(
                {
                    "bvid": output_data["metadata"]["bvid"],
                    "before_count": before,
                    "scraped_count": output_data["metadata"]["comment_total_count"],
                    "after_count": payload["metadata"]["comment_total_count"],
                    "active_count": payload["metadata"].get("active_comment_count"),
                    "deleted_count": payload["metadata"].get("deleted_comment_count"),
                    "danmaku_count": len(danmaku_result.get("items") or []),
                    "video": next(
                        (
                            item
                            for item in list_video_summaries(db_path)
                            if item["bvid"] == output_data["metadata"]["bvid"]
                        ),
                        None,
                    ),
                    "logs": logs[-12:],
                }
            )
        except ValueError as exc:
            fail_progress("parse", bvid if "bvid" in locals() else "", str(exc))
            log_event(
                "task.parse.input_error",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                bvid=bvid if "bvid" in locals() else "",
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            payload, status = api_error_response(exc)
            fail_progress("parse", bvid if "bvid" in locals() else "", payload["error"])
            log_exception(
                "task.parse.error",
                payload["error"],
                request_id=getattr(self, "request_id", ""),
                bvid=bvid if "bvid" in locals() else "",
                status=status,
            )
            self.send_json(payload, status=status)
        finally:
            refresh_lock.release()

    def handle_space_archive_api(self):
        body = self.read_json_body()
        db_path = self.resolve_db_path_from_body(body)
        owner_ref = (body.get("mid") or body.get("url") or body.get("owner_ref") or "").strip()
        mid = extract_space_mid(owner_ref)
        if not mid:
            log_event(
                "task.space_archive.invalid_input",
                "space archive request missing owner mid",
                request_id=getattr(self, "request_id", ""),
                level="warning",
            )
            self.send_json({"error": "请输入 UP 主主页链接或 mid"}, status=400)
            return

        options = {
            "delay": clamp_float(parse_float(body.get("delay"), 1.0), 0.0, 5.0),
            "between_videos_min": clamp_float(parse_float(body.get("between_videos_min"), 8.0), 0.0, 3600.0),
            "between_videos_max": clamp_float(parse_float(body.get("between_videos_max"), 20.0), 0.0, 3600.0),
            "no_cache": bool(body.get("no_cache")),
        }
        if options["between_videos_max"] < options["between_videos_min"]:
            options["between_videos_max"] = options["between_videos_min"]

        task = enqueue_space_task(
            db_path=db_path,
            mid=mid,
            owner_ref=owner_ref,
            options=options,
            request_id=getattr(self, "request_id", ""),
        )
        log_event(
            "task.space_archive.queued",
            "space archive task queued",
            request_id=getattr(self, "request_id", ""),
            mid=mid,
            task_id=task["id"],
            queue_position=task["queue_position"],
            **options,
        )
        self.send_json(
            {
                "ok": True,
                "mid": mid,
                "task_id": task["id"],
                "queue_position": task["queue_position"],
                "message": "UP 主全部视频归档任务已加入队列",
                **options,
            },
            status=202,
        )

    def handle_database_export_api(self):
        body = self.read_json_body()
        db_path = self.resolve_db_path_from_body(body)
        bvids = body.get("bvids")
        bvid = (body.get("bvid") or "").strip()
        owner_mid = (body.get("owner_mid") or "").strip()
        label = (body.get("label") or body.get("owner_name") or bvid or owner_mid or "archive").strip()
        if isinstance(bvids, list):
            selected_bvids = [str(item).strip() for item in bvids if str(item).strip()]
        else:
            selected_bvids = []
        if bvid:
            selected_bvids = [bvid]
        if not selected_bvids and not owner_mid:
            self.send_json({"error": "请选择要导出的 UP 或视频"}, status=400)
            return
        if owner_mid and not bvid:
            selected_bvids = []

        target_path = export_database_path(label, self.database_dir)
        try:
            result = export_archive_to_sqlite(
                db_path,
                target_path,
                bvids=selected_bvids or None,
                owner_mid=owner_mid or None,
            )
        except LookupError as exc:
            log_event(
                "api.database_export.not_found",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                owner_mid=owner_mid,
                bvid=bvid,
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=404)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            log_exception(
                "api.database_export.error",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                owner_mid=owner_mid,
                bvid=bvid,
            )
            self.send_json({"error": str(exc)}, status=500)
            return

        log_event(
            "api.database_export.finish",
            "exported archive database",
            request_id=getattr(self, "request_id", ""),
            path=result["path"],
            source_db=str(db_path),
            video_count=len(result["bvids"]),
            size_bytes=result["size_bytes"],
            counts=result["counts"],
        )
        self.send_json(
            {
                "ok": True,
                "path": result["path"],
                "relative_path": str(Path(result["path"]).resolve().relative_to(ROOT)),
                "file_name": Path(result["path"]).name,
                "database": database_info_for_path(Path(result["path"]), self.db_path, self.database_dir),
                "video_count": len(result["bvids"]),
                "bvids": result["bvids"],
                "counts": result["counts"],
                "size_bytes": result["size_bytes"],
            }
        )

    def handle_database_import_api(self):
        body = self.read_json_body()
        source_value = (body.get("path") or body.get("source_path") or "").strip()
        if not source_value:
            self.send_json({"error": "请输入要导入的 SQLite 数据库路径"}, status=400)
            return
        source_path = Path(source_value).expanduser().resolve()
        try:
            target_path = import_database_file(source_path, self.database_dir)
            info = database_info_for_path(target_path, self.db_path, self.database_dir)
        except (LookupError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            log_exception(
                "api.databases.import_error",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                source_path=str(source_path),
            )
            self.send_json({"error": str(exc)}, status=500)
            return
        log_event(
            "api.databases.import_finish",
            "imported database",
            request_id=getattr(self, "request_id", ""),
            source_path=str(source_path),
            target_path=str(target_path),
            database_id=info["id"],
        )
        self.send_json({"ok": True, "database": info})

    def handle_comments_api(self, parsed):
        query = parse_qs(parsed.query)
        bvid = query.get("bvid", [None])[0]
        db_path = self.resolve_db_path_from_query(parsed)
        try:
            payload = load_comment_data(db_path, bvid=bvid)
            log_event(
                "api.comments.load",
                "loaded comment data",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                bvid=payload["metadata"]["bvid"],
                comment_count=payload["metadata"]["comment_total_count"],
                active_count=payload["metadata"].get("active_comment_count"),
                deleted_count=payload["metadata"].get("deleted_comment_count"),
            )
        except LookupError as exc:
            log_event(
                "api.comments.not_found",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                bvid=bvid or "",
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            log_exception("api.comments.error", str(exc), request_id=getattr(self, "request_id", ""), bvid=bvid or "")
            self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json(payload)

    def handle_danmaku_api(self, parsed):
        query = parse_qs(parsed.query)
        bvid = query.get("bvid", [None])[0]
        limit = parse_optional_int(query.get("limit", [None])[0])
        db_path = self.resolve_db_path_from_query(parsed)
        try:
            payload = load_danmaku_data(db_path, bvid=bvid, limit=limit)
            log_event(
                "api.danmaku.load",
                "loaded danmaku data",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                bvid=payload["metadata"]["bvid"],
                total_count=payload["metadata"]["total_count"],
                limit=limit,
            )
        except LookupError as exc:
            log_event(
                "api.danmaku.not_found",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                bvid=bvid or "",
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            log_exception("api.danmaku.error", str(exc), request_id=getattr(self, "request_id", ""), bvid=bvid or "")
            self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json(payload)

    def handle_refresh_api(self, parsed):
        if not refresh_lock.acquire(blocking=False):
            log_event(
                "task.rejected",
                "comment refresh rejected because another task is active",
                request_id=getattr(self, "request_id", ""),
                kind="comments",
                reason="busy",
            )
            self.send_json({"error": "已有刷新任务正在进行，请稍后再试"}, status=409)
            return

        query = parse_qs(parsed.query)
        requested_bvid = query.get("bvid", [None])[0]
        delay = parse_float(query.get("delay", [None])[0], 0.35)
        db_path = self.resolve_db_path_from_query(parsed)
        try:
            current = load_comment_data(db_path, bvid=requested_bvid)
            video_ref = current["metadata"]["source_url"] or current["metadata"]["bvid"]
            before_count = current["metadata"]["comment_total_count"]
            log_event(
                "task.comments_refresh.start",
                "comment refresh started",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                bvid=current["metadata"]["bvid"],
                before_count=before_count,
                delay=delay,
            )
            start_progress("comments", current["metadata"]["bvid"], "正在重新抓取评论")
            logs = []
            log = make_progress_logger("comments", current["metadata"]["bvid"], logs)

            output_data = scrape_comments(
                video_ref,
                cookie_file=str(DEFAULT_COOKIE_FILE),
                delay=delay,
                logger=log,
            )
            scraped_count = output_data["metadata"]["comment_total_count"]
            update_progress("comments", current["metadata"]["bvid"], "评论抓取完成，正在保存档案")
            save_comments_to_sqlite(output_data, db_path, replace=True)
            payload = load_comment_data(db_path, bvid=output_data["metadata"]["bvid"])
            payload["refresh"] = {
                "before_count": before_count,
                "scraped_count": scraped_count,
                "after_count": payload["metadata"]["comment_total_count"],
                "active_count": payload["metadata"].get("active_comment_count"),
                "deleted_count": payload["metadata"].get("deleted_comment_count"),
                "added_count": payload["metadata"]["comment_total_count"] - before_count,
                "logs": logs[-12:],
            }
            finish_progress("comments", output_data["metadata"]["bvid"], "评论刷新完成")
            log_event(
                "task.comments_refresh.finish",
                "comment refresh finished",
                request_id=getattr(self, "request_id", ""),
                bvid=output_data["metadata"]["bvid"],
                before_count=before_count,
                scraped_count=scraped_count,
                after_count=payload["metadata"]["comment_total_count"],
                active_count=payload["metadata"].get("active_comment_count"),
                deleted_count=payload["metadata"].get("deleted_comment_count"),
            )
        except LookupError as exc:
            fail_progress("comments", requested_bvid or "", str(exc))
            log_event(
                "task.comments_refresh.not_found",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                bvid=requested_bvid or "",
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            payload, status = api_error_response(exc)
            fail_progress("comments", requested_bvid or "", payload["error"])
            log_exception(
                "task.comments_refresh.error",
                payload["error"],
                request_id=getattr(self, "request_id", ""),
                bvid=requested_bvid or "",
                status=status,
            )
            self.send_json(payload, status=status)
            return
        finally:
            refresh_lock.release()

        self.send_json(payload)

    def handle_danmaku_refresh_api(self, parsed):
        if not refresh_lock.acquire(blocking=False):
            log_event(
                "task.rejected",
                "danmaku refresh rejected because another task is active",
                request_id=getattr(self, "request_id", ""),
                kind="danmaku",
                reason="busy",
            )
            self.send_json({"error": "已有抓取任务正在进行，请稍后再试"}, status=409)
            return

        query = parse_qs(parsed.query)
        requested_bvid = query.get("bvid", [None])[0]
        db_path = self.resolve_db_path_from_query(parsed)
        try:
            current = load_comment_data(db_path, bvid=requested_bvid)
            log_event(
                "task.danmaku_refresh.start",
                "danmaku refresh started",
                request_id=getattr(self, "request_id", ""),
                db=str(db_path),
                bvid=current["metadata"]["bvid"],
            )
            start_progress("danmaku", current["metadata"]["bvid"], "正在重新抓取弹幕")
            logs = []
            log = make_progress_logger("danmaku", current["metadata"]["bvid"], logs)

            before_count = load_danmaku_data(
                db_path,
                bvid=current["metadata"]["bvid"],
                limit=0,
            )["metadata"]["total_count"]
            danmaku_result = scrape_danmaku(
                current["metadata"]["bvid"],
                current["video_raw"],
                logger=log,
            )
            scraped_count = len(danmaku_result.get("items") or [])
            warning = ""
            if scraped_count == 0 and before_count > 0:
                warning = "本次弹幕接口返回 0 条，已保留上一次的本地弹幕档案"
                log(f"danmaku: got=0, kept previous archive count={before_count}")
                log_event(
                    "task.danmaku_refresh.empty_result_kept",
                    warning,
                    request_id=getattr(self, "request_id", ""),
                    bvid=current["metadata"]["bvid"],
                    before_count=before_count,
                    scraped_count=scraped_count,
                    level="warning",
                )
            else:
                update_progress("danmaku", current["metadata"]["bvid"], "弹幕抓取完成，正在保存档案")
                save_danmaku_to_sqlite(danmaku_result, db_path, replace=True)
            payload = load_danmaku_data(db_path, bvid=current["metadata"]["bvid"], limit=None)
            payload["refresh"] = {
                "before_count": before_count,
                "after_count": payload["metadata"]["total_count"],
                "scraped_count": scraped_count,
                "logs": logs[-12:],
            }
            if warning:
                payload["refresh"]["warning"] = warning
            finish_progress("danmaku", current["metadata"]["bvid"], warning or "弹幕刷新完成")
            log_event(
                "task.danmaku_refresh.finish",
                "danmaku refresh finished",
                request_id=getattr(self, "request_id", ""),
                bvid=current["metadata"]["bvid"],
                before_count=before_count,
                scraped_count=scraped_count,
                after_count=payload["metadata"]["total_count"],
                warning=warning,
            )
        except LookupError as exc:
            fail_progress("danmaku", requested_bvid or "", str(exc))
            log_event(
                "task.danmaku_refresh.not_found",
                str(exc),
                request_id=getattr(self, "request_id", ""),
                bvid=requested_bvid or "",
                level="warning",
            )
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            payload, status = api_error_response(exc)
            fail_progress("danmaku", requested_bvid or "", payload["error"])
            log_exception(
                "task.danmaku_refresh.error",
                payload["error"],
                request_id=getattr(self, "request_id", ""),
                bvid=requested_bvid or "",
                status=status,
            )
            self.send_json(payload, status=status)
            return
        finally:
            refresh_lock.release()

        self.send_json(payload)

    def handle_static(self, path):
        relative = path.lstrip("/")
        file_path = (self.static_dir / relative).resolve()
        static_root = self.static_dir.resolve()
        if path == "/" or not str(file_path).startswith(str(static_root)):
            file_path = static_root / "index.html"
        if not file_path.exists() or file_path.is_dir():
            file_path = static_root / "index.html"

        try:
            content = file_path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_response(self, code, message=None):
        self.response_status = code
        super().send_response(code, message)

    def send_error(self, code, message=None, explain=None):
        self.response_status = code
        log_event(
            "http.request.error_response",
            message or f"HTTP {code}",
            request_id=getattr(self, "request_id", ""),
            method=getattr(self, "command", ""),
            path=urlparse(self.path).path,
            status=code,
        )
        super().send_error(code, message, explain)

    def send_json(self, payload, status=200):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return parse_json_object_body(raw)

    def resolve_db_path_from_query(self, parsed=None):
        parsed = parsed or urlparse(self.path)
        query = parse_qs(parsed.query)
        return resolve_database_path(query.get("db_id", [None])[0], self.db_path, self.database_dir)

    def resolve_db_path_from_body(self, body):
        return resolve_database_path(body.get("db_id"), self.db_path, self.database_dir)

    def log_message(self, fmt, *args):
        safe_print(f"{self.address_string()} - {fmt % args}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_json_object_body(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequestError("请求体必须是 UTF-8 编码的 JSON") from exc
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadRequestError("请求体不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise BadRequestError("请求体 JSON 必须是对象")
    return payload


def resolve_database_path(db_id, main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR):
    db_id = (str(db_id or "main")).strip() or "main"
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    if db_id == "main":
        return main_db_path
    prefix, _, name = db_id.partition(":")
    if prefix not in {"db", "legacy"} or not name:
        raise BadRequestError("数据库标识无效")
    base_dir = database_dir if prefix == "db" else LEGACY_EXPORT_DIR
    candidate = (base_dir / name).resolve()
    if not is_path_inside(candidate, base_dir.resolve()):
        raise BadRequestError("数据库路径无效")
    if candidate.suffix.lower() not in DATABASE_EXTENSIONS:
        raise BadRequestError("只支持 .db / .sqlite / .sqlite3 数据库")
    if not candidate.exists():
        raise BadRequestError("数据库不存在，请刷新数据库列表")
    return candidate


def list_database_catalog(main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR):
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    database_dir.mkdir(parents=True, exist_ok=True)
    databases = [database_info_for_path(main_db_path, main_db_path, database_dir, db_id="main", role="main")]
    seen = {main_db_path}

    for base_dir, prefix, role in ((database_dir, "db", "hotplug"), (LEGACY_EXPORT_DIR, "legacy", "legacy_export")):
        base_dir = Path(base_dir).resolve()
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in DATABASE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            databases.append(
                database_info_for_path(
                    resolved,
                    main_db_path,
                    database_dir,
                    db_id=f"{prefix}:{path.name}",
                    role=role,
                )
            )
    return databases


def database_info_for_path(path, main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR, db_id=None, role=None):
    path = Path(path).resolve()
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    if db_id is None:
        if path == main_db_path:
            db_id = "main"
        elif is_path_inside(path, database_dir):
            db_id = f"db:{path.name}"
        elif is_path_inside(path, LEGACY_EXPORT_DIR):
            db_id = f"legacy:{path.name}"
        else:
            db_id = f"file:{path.name}"
    if role is None:
        role = "main" if db_id == "main" else "hotplug"

    info = {
        "id": db_id,
        "role": role,
        "name": "主数据库" if db_id == "main" else path.stem,
        "file_name": path.name,
        "path": str(path),
        "relative_path": relative_to_root(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "video_count": 0,
        "comment_count": 0,
        "danmaku_count": 0,
        "owner_count": 0,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else "",
        "ok": False,
        "error": "",
    }
    if not path.exists():
        info["error"] = "文件不存在"
        return info
    try:
        conn = connect(path)
        try:
            ensure_schema(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM videos) AS video_count,
                    (SELECT COUNT(*) FROM comments) AS comment_count,
                    (SELECT COUNT(*) FROM danmaku) AS danmaku_count,
                    (SELECT COUNT(DISTINCT owner_mid) FROM videos WHERE owner_mid IS NOT NULL AND owner_mid <> '') AS owner_count
                """
            ).fetchone()
            info.update(
                {
                    "video_count": row["video_count"] or 0,
                    "comment_count": row["comment_count"] or 0,
                    "danmaku_count": row["danmaku_count"] or 0,
                    "owner_count": row["owner_count"] or 0,
                    "ok": True,
                }
            )
        finally:
            conn.close()
    except Exception as exc:
        info["error"] = str(exc)
    return info


def import_database_file(source_path, database_dir=DEFAULT_DATABASE_DIR):
    source_path = Path(source_path).expanduser().resolve()
    database_dir = Path(database_dir).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise LookupError("导入文件不存在")
    if source_path.suffix.lower() not in DATABASE_EXTENSIONS:
        raise ValueError("只支持 .db / .sqlite / .sqlite3 数据库")
    info = database_info_for_path(source_path)
    if not info["ok"]:
        raise ValueError(f"不是可用的归档数据库：{info['error']}")
    database_dir.mkdir(parents=True, exist_ok=True)
    if is_path_inside(source_path, database_dir):
        return source_path
    target_path = unique_database_path(database_dir / normalize_database_filename(source_path.name))
    shutil.copy2(source_path, target_path)
    return target_path


def normalize_database_filename(name):
    path = Path(name)
    suffix = path.suffix.lower() if path.suffix.lower() in DATABASE_EXTENSIONS else ".db"
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", path.stem).strip("._-") or "archive"
    return f"{stem[:100]}{suffix}"


def unique_database_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time() * 1000)}{path.suffix}")


def is_path_inside(path, directory):
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False


def relative_to_root(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(path).resolve())


def fetch_space_videos(mid, cookie, cache_path=None, use_cache=True):
    if use_cache and cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        items = cached.get("items") if isinstance(cached, dict) else None
        if isinstance(items, list):
            log_event("task.space_archive.cache_hit", "loaded cached UP video list", mid=mid, total=len(items))
            return items

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://space.bilibili.com/{mid}/video",
        "Origin": "https://space.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    client = scraper.BilibiliClient(headers, use_proxy=False)
    mixin = scraper.get_wbi_mixin_key(client, lambda message: update_progress("space", mid, message))
    endpoint = "https://api.bilibili.com/x/space/wbi/arc/search"
    items = []
    page = 1
    while True:
        params = scraper.sign_wbi_params(
            {
                "mid": mid,
                "pn": page,
                "ps": 30,
                "tid": 0,
                "order": "pubdate",
                "platform": "web",
                "web_location": 1550101,
            },
            mixin,
        )
        payload = client.request_json(scraper.build_url(endpoint, params), timeout=30)
        data = payload.get("data") or {}
        vlist = ((data.get("list") or {}).get("vlist") or [])
        total = (data.get("page") or {}).get("count") or 0
        update_progress("space", mid, f"UP视频列表页 page={page} got={len(vlist)} total={total}")
        items.extend(vlist)
        if not vlist or len(items) >= total:
            break
        page += 1
        time.sleep(random.uniform(2.0, 5.0))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "mid": str(mid),
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "total": len(items),
                    "items": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return items


def db_status(db_path, mid):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        rows = conn.execute(
            """
            SELECT
                v.bvid,
                v.fetched_at,
                v.video_cid,
                v.api_comment_count,
                v.stat_reply,
                v.stat_danmaku,
                COALESCE(c.comments, 0) AS comments,
                COALESCE(d.danmaku, 0) AS danmaku
            FROM videos v
            LEFT JOIN (
                SELECT bvid, COUNT(*) AS comments
                FROM comments
                GROUP BY bvid
            ) c ON c.bvid = v.bvid
            LEFT JOIN (
                SELECT bvid, COUNT(*) AS danmaku
                FROM danmaku
                GROUP BY bvid
            ) d ON d.bvid = v.bvid
            WHERE v.owner_mid = ?
            """,
            (str(mid),),
        ).fetchall()
        return {
            row["bvid"]: {
                "fetched_at": row["fetched_at"],
                "video_cid": row["video_cid"],
                "api_comment_count": row["api_comment_count"],
                "stat_reply": row["stat_reply"],
                "stat_danmaku": row["stat_danmaku"],
                "comments": row["comments"] or 0,
                "danmaku": row["danmaku"] or 0,
            }
            for row in rows
        }
    finally:
        conn.close()


def is_complete(item, status):
    bvid = item.get("bvid")
    saved = status.get(bvid or "")
    if not saved or not saved.get("fetched_at"):
        return False

    expected_comments = first_int(item.get("comment"), saved.get("stat_reply"), saved.get("api_comment_count"))
    expected_danmaku = first_int(item.get("video_review"), saved.get("stat_danmaku"))

    comments_complete = (
        expected_comments == 0
        or saved["comments"] > 0
        or saved.get("api_comment_count") == 0
    )
    danmaku_complete = expected_danmaku == 0 or saved["danmaku"] > 0
    return bool(comments_complete and danmaku_complete)


def run_space_queue_task(task):
    refresh_lock.acquire()
    try:
        space_task_queue.update(
            task,
            status="running",
            started_at=utc_now(),
            message="正在抓取",
        )
        start_progress("space", task["mid"], f"准备抓取 UP {task['mid']} 的视频列表")
        run_space_archive_task(task)
    finally:
        refresh_lock.release()


space_task_queue = InMemoryTaskQueue("space", run_space_queue_task)


def enqueue_space_task(db_path, mid, owner_ref, options, request_id=""):
    return space_task_queue.enqueue(
        {
            "mid": str(mid),
            "owner_ref": owner_ref,
            "request_id": request_id,
            "db_path": str(db_path),
            "options": dict(options),
        }
    )


def get_space_queue_snapshot():
    return space_task_queue.snapshot()


def update_space_task(task, **fields):
    space_task_queue.update(task, **fields)


def run_space_archive_task(task):
    db_path = task["db_path"]
    mid = task["mid"]
    options = task["options"]
    request_id = task.get("request_id", "")
    cache_path = DEFAULT_SPACE_CACHE_DIR / f"space_{mid}_videos.json"
    cookie = scraper.load_cookie_file(DEFAULT_COOKIE_FILE) if DEFAULT_COOKIE_FILE.exists() else ""
    total = 0
    complete = 0
    archived = 0
    skipped = 0
    failed = 0
    current_bvid = ""
    try:
        log_event(
            "task.space_archive.start",
            "space archive task started",
            request_id=request_id,
            mid=mid,
            task_id=task["id"],
            **options,
        )
        update_progress("space", mid, f"正在读取 UP {mid} 的视频列表")
        update_space_task(task, message="正在读取视频列表", progress=5)
        items = fetch_space_videos(
            mid,
            cookie,
            cache_path=cache_path,
            use_cache=not options.get("no_cache"),
        )
        total = len(items)
        update_space_task(task, total=total, message=f"视频列表完成，共 {total} 个视频")
        update_progress("space", mid, f"UP视频列表完成 total={total} complete=0 archived=0 skipped=0 failed=0")
        status = db_status(db_path, mid)
        complete = sum(1 for video in items if is_complete(video, status))
        for index, item in enumerate(items, start=1):
            current_bvid = item.get("bvid") or ""
            if is_complete(item, status):
                skipped += 1
                update_space_task(
                    task,
                    current_bvid=current_bvid,
                    total=total,
                    complete=complete,
                    archived=archived,
                    skipped=skipped,
                    failed=failed,
                    progress=space_task_percent(index, total),
                    message=f"跳过已完成视频 {index}/{total}",
                )
                update_progress(
                    "space",
                    current_bvid or mid,
                    f"UP视频跳过 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
                )
                continue

            update_space_task(
                task,
                current_bvid=current_bvid,
                total=total,
                complete=complete,
                archived=archived,
                skipped=skipped,
                failed=failed,
                progress=space_task_percent(index, total),
                message=f"正在抓取视频 {index}/{total}",
            )
            update_progress(
                "space",
                current_bvid or mid,
                f"UP视频抓取 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
            )
            try:
                comments = scrape_comments(
                    current_bvid,
                    cookie=cookie,
                    cookie_file=str(DEFAULT_COOKIE_FILE),
                    delay=options.get("delay", 1.0),
                    logger=lambda message, bvid=current_bvid: log_space_video_progress(bvid, message),
                    max_main_pages=None,
                    fetch_children=True,
                )
                update_space_task(task, message=f"正在保存评论 {index}/{total}")
                update_progress("space", current_bvid, f"UP视频保存评论 {index}/{total} bvid={current_bvid}")
                save_comments_to_sqlite(comments, db_path, replace=False)

                headers = scraper.make_headers(current_bvid, cookie)
                danmaku_result = scrape_danmaku(
                    current_bvid,
                    comments.get("video_raw"),
                    headers=headers,
                    logger=lambda message, bvid=current_bvid: log_space_video_progress(bvid, message),
                    fetch_likes=True,
                )
                if danmaku_result.get("items"):
                    update_space_task(task, message=f"正在保存弹幕 {index}/{total}")
                    update_progress("space", current_bvid, f"UP视频保存弹幕 {index}/{total} bvid={current_bvid}")
                    save_danmaku_to_sqlite(danmaku_result, db_path, replace=True)
                else:
                    update_progress("space", current_bvid, f"UP视频弹幕为空已跳过保存 {index}/{total} bvid={current_bvid}")

                archived += 1
                status[current_bvid] = {
                    "api_comment_count": comments.get("metadata", {}).get("api_comment_count"),
                    "comments": len(comments.get("comment_items") or []),
                    "danmaku": len(danmaku_result.get("items") or []),
                }
                complete += 1
                update_space_task(
                    task,
                    complete=complete,
                    archived=archived,
                    skipped=skipped,
                    failed=failed,
                    progress=space_task_percent(index, total),
                    message=f"视频完成 {index}/{total}",
                )
                log_event(
                    "task.space_archive.video_finish",
                    "space archive video finished",
                    request_id=request_id,
                    mid=mid,
                    task_id=task["id"],
                    bvid=current_bvid,
                    index=index,
                    total=total,
                    archived=archived,
                    complete=complete,
                    failed=failed,
                )
            except Exception as exc:
                if should_abort_space_archive(exc):
                    raise
                failed += 1
                payload, status_code = api_error_response(exc)
                update_space_task(
                    task,
                    failed=failed,
                    current_bvid=current_bvid,
                    progress=space_task_percent(index, total),
                    message=f"视频失败，已跳过 {index}/{total}",
                )
                update_progress(
                    "space",
                    current_bvid or mid,
                    f"UP视频失败 {index}/{total} complete={complete} archived={archived} skipped={skipped} failed={failed} bvid={current_bvid}",
                )
                log_exception(
                    "task.space_archive.video_error",
                    payload["error"],
                    request_id=request_id,
                    mid=mid,
                    task_id=task["id"],
                    bvid=current_bvid,
                    index=index,
                    total=total,
                    complete=complete,
                    archived=archived,
                    skipped=skipped,
                    failed=failed,
                    status=status_code,
                )
            if index < total:
                pause = random.uniform(options.get("between_videos_min", 8.0), options.get("between_videos_max", 20.0))
                update_space_task(task, message=f"等待下一条 {index}/{total}")
                update_progress("space", current_bvid, f"UP视频间隔 {index}/{total} seconds={pause:.1f} next={index + 1}")
                time.sleep(pause)

        status = db_status(db_path, mid)
        complete = sum(1 for video in items if is_complete(video, status))
        update_space_task(
            task,
            status="finished",
            message=f"已完成 {complete}/{total}",
            finished_at=utc_now(),
            total=total,
            complete=complete,
            archived=archived,
            skipped=skipped,
            failed=failed,
            progress=100,
        )
        finish_progress("space", mid, f"UP 主归档完成：{complete}/{total} 个视频已有评论和弹幕，失败 {failed} 个")
        log_event(
            "task.space_archive.finish",
            "space archive task finished",
            request_id=request_id,
            mid=mid,
            task_id=task["id"],
            total=total,
            complete=complete,
            archived=archived,
            skipped=skipped,
            failed=failed,
        )
    except Exception as exc:
        payload, status_code = api_error_response(exc)
        update_space_task(
            task,
            status="failed",
            message=payload["error"],
            finished_at=utc_now(),
            current_bvid=current_bvid,
            total=total,
            complete=complete,
            archived=archived,
            skipped=skipped,
            failed=failed,
        )
        fail_progress("space", current_bvid or mid, payload["error"])
        log_exception(
            "task.space_archive.error",
            payload["error"],
            request_id=request_id,
            mid=mid,
            task_id=task["id"],
            bvid=current_bvid,
            total=total,
            complete=complete,
            archived=archived,
            skipped=skipped,
            failed=failed,
            status=status_code,
        )


def space_task_percent(index, total):
    if not total:
        return 0
    return min(99, max(1, int((index / total) * 100)))


def log_space_video_progress(bvid, message):
    if (
        message.startswith("main page")
        or message.startswith("main page limit")
        or message.startswith("skipping children")
        or message.startswith("danmaku:")
        or message.startswith("parsed xml")
        or message.startswith("fetching xml")
        or message.startswith("warmup:")
        or message.startswith("wbi:")
        or message.startswith("video info:")
        or message.startswith("video:")
        or message.startswith("main replies:")
        or message.startswith("warning:")
        or message.startswith("comments closed:")
        or "slow request" in message
    ):
        update_progress("space", bvid, message)


def start_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        progress_state.update(
            {
                "active": True,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": [message],
                "percent": progress_percent(kind, message),
                "stage": progress_stage(kind, message),
                "stats": progress_stats(kind, message, {}),
                "started_at": now,
                "updated_at": now,
                "done": False,
                "error": "",
            }
        )
    log_event(
        "progress.start",
        message,
        kind=kind,
        bvid=bvid or "",
        percent=progress_percent(kind, message),
        stage=progress_stage(kind, message),
    )


def update_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        logs = [*progress_state.get("logs", []), message][-80:]
        stats = progress_stats(kind, message, progress_state.get("stats", {}))
        progress_state.update(
            {
                "active": True,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": progress_percent(kind, message, progress_state.get("percent", 0)),
                "stage": progress_stage(kind, message),
                "stats": stats,
                "updated_at": now,
                "done": False,
                "error": "",
            }
        )
        percent = progress_state.get("percent", 0)
        stage = progress_state.get("stage", "")
        stats = dict(progress_state.get("stats", {}))
    log_event(
        "progress.update",
        message,
        kind=kind,
        bvid=bvid or "",
        percent=percent,
        stage=stage,
        stats=stats,
    )


def finish_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        logs = [*progress_state.get("logs", []), message][-80:]
        progress_state.update(
            {
                "active": False,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": 100,
                "stage": "完成",
                "stats": progress_state.get("stats", {}),
                "updated_at": now,
                "done": True,
                "error": "",
            }
        )
    log_event(
        "progress.finish",
        message,
        kind=kind,
        bvid=bvid or "",
        percent=100,
        stage="完成",
    )


def fail_progress(kind, bvid, message):
    now = utc_now()
    stage = progress_stage(kind, message)
    with progress_lock:
        logs = [*progress_state.get("logs", []), f"失败：{message}"][-80:]
        progress_state.update(
            {
                "active": False,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": progress_state.get("percent", 0),
                "stage": stage,
                "stats": progress_state.get("stats", {}),
                "updated_at": now,
                "done": True,
                "error": message,
            }
        )
        percent = progress_state.get("percent", 0)
    log_event(
        "progress.fail",
        message,
        kind=kind,
        bvid=bvid or "",
        percent=percent,
        stage=stage,
        level="error",
    )


def get_progress_snapshot():
    with progress_lock:
        snapshot = {
            **progress_state,
            "logs": list(progress_state.get("logs", [])),
            "stats": dict(progress_state.get("stats", {})),
        }
    snapshot["queue"] = get_space_queue_snapshot()
    return snapshot


def make_progress_logger(kind, bvid, logs):
    def log(message):
        logs.append(message)
        update_progress(kind, bvid, message)

    return log


def safe_print(message):
    try:
        print(message, flush=True)
    except OSError:
        pass


def api_error_response(exc):
    message = str(exc)
    lower_message = message.lower()

    if isinstance(exc, scraper.WbiSignatureUnavailableError):
        return (
            {
                "error": "WBI 签名接口暂不可用，已暂停本轮 UP 归档。稍后重新抓取同一个 UP 时，已归档视频会自动跳过。",
                "detail": message,
            },
            502,
        )

    if (
        (isinstance(exc, BilibiliRequestError) and exc.status == 412)
        or "http error 412" in lower_message
    ):
        return (
            {
                "error": "Bilibili 接口返回 412，通常表示当前 Cookie、会话指纹或请求上下文未通过接口预检。工具已重新签名、冷却退避并重试；如果仍失败，请暂停一段时间后再试，必要时更新 Cookie。",
                "detail": message,
            },
            502,
        )

    if (
        (isinstance(exc, BilibiliRequestError) and exc.api_code == -352)
        or "api code=-352" in lower_message
        or "api code -352" in lower_message
    ):
        return (
            {
                "error": "Bilibili 接口返回风控校验失败，通常与请求频率、Cookie 状态或访问环境有关。工具已自动进入长冷却退避；请暂停一段时间后再试。",
                "detail": message,
            },
            502,
        )

    if (
        (isinstance(exc, BilibiliRequestError) and exc.status == 429)
        or "http error 429" in lower_message
    ):
        return (
            {
                "error": "Bilibili 接口返回 429，说明当前访问频率已被明确限制。工具已自动进入长冷却退避；请避免连续手动刷新。",
                "detail": message,
            },
            502,
        )

    if "consecutive_very_slow_requests" in lower_message or "slow_limit_cooldown" in lower_message:
        return (
            {
                "error": "Bilibili 接口响应持续异常变慢，通常是软限流或账号/IP 级降速。工具已进入更长冷却，避免继续把风控时间拉长。",
                "detail": message,
            },
            502,
        )

    if "http error" in lower_message or "request failed after" in lower_message:
        return (
            {
                "error": "Bilibili 接口请求失败，可能是网络、登录态、风控或接口临时不可用。",
                "detail": message,
            },
            502,
        )

    if "[errno 22] invalid argument" in lower_message:
        return (
            {
                "error": "本地服务输出流异常，已避免让日志写入中断抓取。请重启服务后重试。",
                "detail": message,
            },
            500,
        )

    return ({"error": message}, 500)


def should_abort_space_archive(exc):
    lower_message = str(exc).lower()
    return (
        isinstance(exc, scraper.WbiSignatureUnavailableError)
        or scraper.is_blocked_request_error(exc)
        or (isinstance(exc, BilibiliRequestError) and exc.status in {412, 429})
        or "http error 412" in lower_message
        or "http error 429" in lower_message
        or "api code=-352" in lower_message
        or "api code -352" in lower_message
        or "consecutive_very_slow_requests" in lower_message
        or "slow_limit_cooldown" in lower_message
    )


def progress_stage(kind, message):
    if "HTTP 412" in message or "HTTP 429" in message or "cooling down" in message:
        return "接口冷却"
    if kind == "space" and ("暂停" in message or "暂不可用" in message):
        return "暂停归档"
    if kind == "space" and "UP视频失败" in message:
        return "跳过失败视频"
    if "失败" in message:
        return "失败"
    if "保存" in message:
        return "保存档案"
    if "likes" in message or "点赞" in message:
        return "弹幕点赞"
    if "parsed xml" in message:
        return "解析弹幕"
    if "fetching xml" in message or "正在重新抓取弹幕" in message or "正在抓取弹幕" in message:
        return "抓取弹幕"
    if message.startswith("main page"):
        return "抓取主评论"
    if "fetching children" in message or "children done" in message or "child root" in message:
        return "抓取楼中楼"
    if kind == "space":
        if "视频列表" in message:
            return "读取UP视频"
        if "保存评论" in message or "保存弹幕" in message:
            return "保存档案"
        if "弹幕" in message or "fetching xml" in message or "parsed xml" in message:
            return "抓取弹幕"
        if "跳过" in message:
            return "跳过已完成"
        if "间隔" in message:
            return "等待下一条"
        return "归档UP视频"
    if "评论抓取完成" in message:
        return "保存评论"
    if kind == "parse" and "准备解析" in message:
        return "解析视频"
    return "进行中"


def progress_percent(kind, message, current=0):
    if kind == "space":
        if "UP 主归档完成" in message:
            return 100
        if "视频列表" in message:
            return max(current, 5)
        index, total = parse_space_progress(message)
        if total:
            return max(current, min(99, 5 + int((index / total) * 94)))
        return max(current, 8)
    if "完成" in message:
        return 100
    if "保存" in message:
        return max(current, 92)
    if kind == "danmaku":
        if "fetching xml" in message:
            return max(current, 20)
        if "parsed xml" in message:
            return max(current, 45)
        batch = re.search(r"batch\s+(\d+)", message)
        if batch:
            return max(current, min(90, 55 + int(batch.group(1)) * 10))
        if "got=" in message:
            return max(current, 88)
    if kind == "parse":
        if message.startswith("main page"):
            page = parse_progress_int(message, r"main page\s+(\d+)")
            return max(current, min(55, 8 + page))
        if "child root" in message or "fetching children" in message or "children done" in message:
            index, total = parse_child_root_progress(message)
            if total:
                return max(current, min(76, 56 + int((index / total) * 20)))
            return max(current, min(76, current + 1))
        if "正在抓取弹幕" in message:
            return max(current, 78)
        if "danmaku likes" in message:
            return max(current, min(94, current + 4))
    if kind == "comments":
        if message.startswith("main page"):
            page = parse_progress_int(message, r"main page\s+(\d+)")
            return max(current, min(65, 10 + page))
        if "child root" in message or "fetching children" in message or "children done" in message:
            index, total = parse_child_root_progress(message)
            if total:
                return max(current, min(90, 66 + int((index / total) * 24)))
            return max(current, min(90, current + 2))
        if "评论抓取完成" in message:
            return max(current, 92)
    return max(current, 8)


def progress_stats(kind, message, current):
    stats = dict(current or {})
    if kind in {"comments", "parse"}:
        main = re.search(r"main page\s+(\d+): got=(\d+) unique=(\d+) all_count=([^ ]+)", message)
        if main:
            stats["主评论页"] = main.group(1)
            stats["本页评论"] = main.group(2)
            stats["已抓评论"] = main.group(3)
            if main.group(4) != "None":
                stats["接口总数"] = main.group(4)
        child_batch = re.search(r"fetching children batch: roots=(\d+) workers=(\d+) total_fetched=(\d+) total_expected=(\d+)", message)
        if child_batch:
            stats["楼中楼进度"] = f"0 / {child_batch.group(1)}"
            stats["楼中楼总已抓"] = child_batch.group(3)
            stats["楼中楼预期总数"] = child_batch.group(4)
            stats["并发数"] = child_batch.group(2)
        child_done = re.search(
            r"children done\s+(\d+)/(\d+)\s+root=([^ ]+)\s+fetched=(\d+)\s+total_fetched=(\d+)\s+total_expected=(\d+)",
            message,
        )
        if child_done:
            stats["楼中楼进度"] = f"{child_done.group(1)} / {child_done.group(2)}"
            stats["当前根评论"] = child_done.group(3)
            stats["当前楼中楼已抓"] = child_done.group(4)
            stats["楼中楼总已抓"] = child_done.group(5)
            stats["楼中楼预期总数"] = child_done.group(6)
        child = re.search(r"child root=.*?unique=(\d+).*?(?:expected|count)=(\d+|None)", message)
        if child:
            stats["当前楼中楼已抓"] = child.group(1)
            if child.group(2) != "None":
                stats["当前楼中楼预期"] = child.group(2)
        child_start = re.search(r"fetching children\s+(\d+)/(\d+)\s+root=([^ ]+)\s+expected=(\d+|None)", message)
        if child_start:
            stats["楼中楼进度"] = f"{child_start.group(1)} / {child_start.group(2)}"
            stats["当前根评论"] = child_start.group(3)
            if child_start.group(4) != "None":
                stats["当前楼中楼预期"] = child_start.group(4)
    if kind in {"danmaku", "parse"}:
        parsed = re.search(r"parsed xml items=(\d+)", message)
        if parsed:
            stats["弹幕条数"] = parsed.group(1)
        got = re.search(r"danmaku: cid=.*? got=(\d+)", message)
        if got:
            stats["弹幕条数"] = got.group(1)
        batch = re.search(r"danmaku likes: batch\s+(\d+) ids=(\d+)", message)
        if batch:
            stats["点赞批次"] = batch.group(1)
            stats["本批 dmid"] = batch.group(2)
    if kind == "space":
        list_done = re.search(r"UP视频列表完成 total=(\d+) complete=(\d+) archived=(\d+) skipped=(\d+)(?: failed=(\d+))?", message)
        if list_done:
            stats["UP视频总数"] = list_done.group(1)
            stats["已完成视频"] = list_done.group(2)
            stats["本次新增"] = list_done.group(3)
            stats["跳过视频"] = list_done.group(4)
            stats["失败视频"] = list_done.group(5) or "0"
        video = re.search(
            r"UP视频(?:抓取|跳过|失败)\s+(\d+)/(\d+).*?complete=(\d+).*?archived=(\d+).*?skipped=(\d+)(?:.*?failed=(\d+))?.*?bvid=([^ ]*)",
            message,
        )
        if video:
            stats["UP视频进度"] = f"{video.group(1)} / {video.group(2)}"
            stats["UP视频总数"] = video.group(2)
            stats["已完成视频"] = video.group(3)
            stats["本次新增"] = video.group(4)
            stats["跳过视频"] = video.group(5)
            if video.group(6) is not None:
                stats["失败视频"] = video.group(6)
            if video.group(7):
                stats["当前视频"] = video.group(7)
        interval = re.search(r"UP视频间隔\s+(\d+)/(\d+)\s+seconds=([0-9.]+)\s+next=(\d+)", message)
        if interval:
            stats["UP视频进度"] = f"{interval.group(1)} / {interval.group(2)}"
            stats["等待秒数"] = interval.group(3)
            stats["下一条序号"] = interval.group(4)
    return stats


def parse_progress_int(message, pattern):
    match = re.search(pattern, message)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def parse_child_root_progress(message):
    match = re.search(r"fetching children\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"children done\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def parse_space_progress(message):
    match = re.search(r"UP视频(?:抓取|跳过|失败|保存评论|保存弹幕|弹幕为空已跳过保存|间隔)\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def parse_float(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def first_int(*values):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def clamp_float(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def clamp_int(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def export_database_path(label, export_dir=DEFAULT_EXPORT_DIR):
    export_dir = Path(export_dir).resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(label or "archive")).strip("._-")
    safe_label = safe_label[:80] or "archive"
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    base_path = export_dir / f"{timestamp}_{safe_label}.db"
    if not base_path.exists():
        return base_path
    for index in range(2, 1000):
        candidate = export_dir / f"{timestamp}_{safe_label}_{index}.db"
        if not candidate.exists():
            return candidate
    return export_dir / f"{timestamp}_{safe_label}_{int(time.time() * 1000)}.db"


def extract_space_mid(value):
    value = (value or "").strip()
    if not value:
        return ""
    url_match = re.search(r"space\.bilibili\.com/(\d+)", value)
    if url_match:
        return url_match.group(1)
    mid_match = re.search(r"^\d{2,}$", value)
    if mid_match:
        return mid_match.group(0)
    return ""


def parse_optional_int(value):
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--static", default=str(DEFAULT_STATIC))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--database-dir", default=str(DEFAULT_DATABASE_DIR))
    parser.add_argument("--log-max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--log-backup-count", type=int, default=10)
    parser.add_argument("--log-queue-size", type=int, default=10000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    configure_logging(
        args.log_dir,
        max_bytes=args.log_max_bytes,
        backup_count=args.log_backup_count,
        queue_size=args.log_queue_size,
        level=args.log_level,
    )

    handler = type(
        "ConfiguredCommentDanmakuServer",
        (CommentDanmakuServer,),
        {
            "db_path": Path(args.db).resolve(),
            "static_dir": Path(args.static).resolve(),
            "log_dir": Path(args.log_dir).resolve(),
            "database_dir": Path(args.database_dir).resolve(),
        },
    )
    handler.db_path = prepare_database_path(handler.db_path)
    handler.database_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    log_event(
        "service.start",
        "Bilibili comment/danmaku service started",
        host=args.host,
        port=args.port,
        db=str(handler.db_path),
        static_dir=str(handler.static_dir),
        log_dir=str(handler.log_dir),
        database_dir=str(handler.database_dir),
        logging=logging_status(),
    )
    safe_print(f"Serving Bilibili comment/danmaku app at http://{args.host}:{args.port}/")
    safe_print(f"SQLite database: {Path(args.db).resolve()}")
    safe_print(f"Hotplug database directory: {handler.database_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("service.stop", "service stopped by keyboard interrupt")
        raise
    finally:
        server.server_close()
        shutdown_logging()


if __name__ == "__main__":
    main()

