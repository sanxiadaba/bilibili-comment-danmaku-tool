import argparse
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from app_logging import configure_logging, logging_status, log_event, log_exception, new_request_id, shutdown_logging
from bilibili_comment_danmaku import (
    export_archive_to_json,
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
from database_registry import (
    DATABASE_EXTENSIONS,
    DEFAULT_DATABASE_DIR,
    DEFAULT_EXPORT_DIR,
    IMPORT_EXTENSIONS,
    LEGACY_EXPORT_DIR,
    database_info_for_path,
    export_database_path,
    import_database_file,
    import_uploaded_database_file,
    list_database_catalog,
    parse_multipart_files,
    public_database_info,
    relative_to_root,
    resolve_database_path,
)
from control_api import control_capabilities, normalize_control_action_payload
from errors import BadRequestError
from progress_state import (
    fail_progress,
    finish_progress,
    get_progress_snapshot,
    make_progress_logger,
    parse_float,
    set_queue_snapshot_provider,
    start_progress,
    update_progress,
)
from space_archive import (
    SpaceArchiveService,
    api_error_response,
    extract_space_mid,
    normalize_space_archive_options,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_STATIC = ROOT / "dist"
DEFAULT_COOKIE_FILE = ROOT / "data" / "cookie.txt"
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_SPACE_CACHE_DIR = ROOT / "data" / "space_cache"
refresh_lock = threading.Lock()
space_archive_service = SpaceArchiveService(DEFAULT_COOKIE_FILE, DEFAULT_SPACE_CACHE_DIR, refresh_lock)
set_queue_snapshot_provider(space_archive_service.snapshot)


class CommentDanmakuServer(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB
    static_dir = DEFAULT_STATIC
    log_dir = DEFAULT_LOG_DIR
    database_dir = DEFAULT_DATABASE_DIR

    def do_GET(self):
        self.start_request_log("GET")
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/v1/control"):
                self.handle_control_get_api(parsed)
                return
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
            if parsed.path.startswith("/api/v1/control"):
                self.handle_control_post_api(parsed)
                return
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
            if parsed.path == "/api/databases/import-file":
                self.handle_database_import_file_api()
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
            self.send_json(
                {"videos": videos, "database": public_database_info(database_info_for_path(db_path, self.db_path, self.database_dir))}
            )
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

    def handle_control_get_api(self, parsed):
        path = parsed.path.rstrip("/")
        if path in {"", "/api/v1/control"}:
            self.send_json(control_capabilities())
            return
        if path in {"/api/v1/control/status", "/api/v1/control/progress"}:
            payload = get_progress_snapshot()
            if path.endswith("/status"):
                payload = {
                    "ok": True,
                    "version": "v1",
                    "health": {
                        "db": str(self.db_path),
                        "database_dir": str(self.database_dir),
                        "logging": logging_status(),
                    },
                    "progress": payload,
                }
            self.send_json(payload)
            return
        if path == "/api/v1/control/databases":
            self.handle_databases_api()
            return
        if path == "/api/v1/control/videos":
            self.handle_videos_api()
            return
        if path == "/api/v1/control/comments":
            self.handle_comments_api(parsed)
            return
        if path == "/api/v1/control/danmaku":
            self.handle_danmaku_api(parsed)
            return
        self.send_json({"error": f"未知控制 API：{parsed.path}"}, status=404)

    def handle_control_post_api(self, parsed):
        path = parsed.path.rstrip("/")
        if path == "/api/v1/control/actions":
            body = self.read_json_body()
            try:
                action, params = normalize_control_action_payload(body)
            except LookupError as exc:
                self.send_json({"error": str(exc), "capabilities": control_capabilities()}, status=404)
                return
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            self.dispatch_control_action(action, params)
            return
        if path == "/api/v1/control/videos/parse":
            self.handle_parse_video_api()
            return
        if path == "/api/v1/control/space/archive":
            self.handle_space_archive_api()
            return
        if path == "/api/v1/control/archive/export":
            self.handle_database_export_api()
            return
        if path == "/api/v1/control/databases/import":
            self.handle_database_import_api()
            return
        if path == "/api/v1/control/comments/refresh":
            body = self.read_json_body()
            self.handle_refresh_api(self.control_query_parsed(parsed, body, ("bvid", "db_id", "delay")))
            return
        if path == "/api/v1/control/danmaku/refresh":
            body = self.read_json_body()
            self.handle_danmaku_refresh_api(self.control_query_parsed(parsed, body, ("bvid", "db_id")))
            return
        self.send_json({"error": f"未知控制 API：{parsed.path}", "capabilities": control_capabilities()}, status=404)

    def dispatch_control_action(self, action, params):
        if action == "videos.parse":
            self.run_with_json_body(params, self.handle_parse_video_api)
            return
        if action == "space.archive":
            self.run_with_json_body(params, self.handle_space_archive_api)
            return
        if action == "archive.export":
            self.run_with_json_body(params, self.handle_database_export_api)
            return
        if action == "databases.import":
            self.run_with_json_body(params, self.handle_database_import_api)
            return
        if action == "comments.refresh":
            parsed = self.control_query_parsed(urlparse(self.path), params, ("bvid", "db_id", "delay"))
            self.handle_refresh_api(parsed)
            return
        if action == "danmaku.refresh":
            parsed = self.control_query_parsed(urlparse(self.path), params, ("bvid", "db_id"))
            self.handle_danmaku_refresh_api(parsed)
            return
        self.send_json({"error": f"不支持的控制动作：{action}"}, status=404)

    def run_with_json_body(self, body, handler):
        original_body = getattr(self, "_json_body_override", None)
        self._json_body_override = dict(body)
        try:
            handler()
        finally:
            if original_body is None:
                self._json_body_override = None
            else:
                self._json_body_override = original_body

    def control_query_parsed(self, parsed, body, keys):
        query = parse_qs(parsed.query)
        for key in keys:
            value = body.get(key)
            if value is not None and value != "":
                query[key] = [str(value)]
        return parsed._replace(query=urlencode({key: values[-1] for key, values in query.items() if values}))

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

        options = normalize_space_archive_options(body)

        task = space_archive_service.enqueue(
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
        export_format = str(body.get("format") or "sqlite").strip().lower()
        if export_format not in {"sqlite", "json"}:
            self.send_json({"error": "导出格式只支持 sqlite 或 json"}, status=400)
            return
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

        target_path = export_database_path(label, self.database_dir, suffix=".json" if export_format == "json" else ".db")
        try:
            exporter = export_archive_to_json if export_format == "json" else export_archive_to_sqlite
            result = exporter(
                db_path,
                target_path,
                bvids=selected_bvids or None,
                owner_mid=owner_mid or None,
                archive_kind="up" if owner_mid and not bvid else "video" if len(selected_bvids) == 1 else "collection",
                label=label,
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
            export_format=export_format,
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
                "format": export_format,
                "json_path": result.get("json_path", ""),
                "json_relative_path": relative_to_root(result["json_path"]) if result.get("json_path") else "",
                "json_file_name": Path(result["json_path"]).name if result.get("json_path") else "",
                "database": public_database_info(database_info_for_path(Path(result["path"]), self.db_path, self.database_dir))
                if export_format == "sqlite"
                else None,
                "video_count": len(result["bvids"]),
                "bvids": result["bvids"],
                "counts": result["counts"],
                "manifest": result.get("manifest") or {},
                "size_bytes": result["size_bytes"],
            }
        )

    def handle_database_import_api(self):
        body = self.read_json_body()
        source_value = (body.get("path") or body.get("source_path") or "").strip()
        if not source_value:
            self.send_json({"error": "请输入要导入的 SQLite 数据库或 JSON 归档路径"}, status=400)
            return
        source_path = Path(source_value).expanduser().resolve()
        try:
            target_path = import_database_file(source_path, self.database_dir)
            info = public_database_info(database_info_for_path(target_path, self.db_path, self.database_dir))
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

    def handle_database_import_file_api(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            files = parse_multipart_files(raw, self.headers.get("Content-Type", ""))
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return

        imported = []
        errors = []
        for item in files:
            filename = item["filename"]
            suffix = Path(filename).suffix.lower()
            if suffix not in IMPORT_EXTENSIONS:
                errors.append(f"{filename}: 只支持 .db / .sqlite / .sqlite3 / .json")
                continue
            try:
                target_path = import_uploaded_database_file(filename, item["content"], self.database_dir)
                imported.append(public_database_info(database_info_for_path(target_path, self.db_path, self.database_dir)))
            except Exception as exc:
                errors.append(f"{filename}: {exc}")

        if not imported:
            self.send_json({"error": "没有导入任何数据库文件", "errors": errors}, status=400)
            return

        log_event(
            "api.databases.import_file_finish",
            "imported uploaded databases",
            request_id=getattr(self, "request_id", ""),
            imported_count=len(imported),
            error_count=len(errors),
        )
        self.send_json(
            {
                "ok": True,
                "database": imported[0],
                "databases": imported,
                "imported_count": len(imported),
                "errors": errors,
            }
        )

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
        if getattr(self, "_json_body_override", None) is not None:
            return dict(self._json_body_override)
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


def safe_print(message):
    try:
        print(message, flush=True)
    except OSError:
        pass


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

