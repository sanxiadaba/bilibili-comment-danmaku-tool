import argparse
import json
import mimetypes
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bilibili_comments import (
    extract_bvid,
    list_video_summaries,
    load_comment_data,
    load_danmaku_data,
    save_danmaku_to_sqlite,
    save_to_sqlite,
    scrape_comments,
    scrape_danmaku,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "comments.db"
DEFAULT_STATIC = ROOT / "dist"
DEFAULT_COOKIE_FILE = ROOT / "cookie.txt"
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


class CommentServer(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB
    static_dir = DEFAULT_STATIC

    def do_GET(self):
        parsed = urlparse(self.path)
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
            self.send_json({"ok": True, "db": str(self.db_path)})
            return
        self.handle_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/videos/parse":
            self.handle_parse_video_api()
            return
        if parsed.path == "/api/danmaku/refresh":
            self.handle_danmaku_refresh_api(parsed)
            return
        if parsed.path == "/api/refresh":
            self.handle_refresh_api(parsed)
            return
        self.send_error(404)

    def handle_videos_api(self):
        try:
            self.send_json({"videos": list_video_summaries(self.db_path)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_progress_api(self):
        self.send_json(get_progress_snapshot())

    def handle_parse_video_api(self):
        if not refresh_lock.acquire(blocking=False):
            self.send_json({"error": "已有抓取任务正在进行，请稍后再试"}, status=409)
            return

        try:
            body = self.read_json_body()
            video_ref = (body.get("url") or body.get("video_ref") or body.get("bvid") or "").strip()
            if not video_ref:
                self.send_json({"error": "请输入 Bilibili 视频链接或 BV 号"}, status=400)
                return
            bvid = extract_bvid(video_ref)
            delay = parse_float(body.get("delay"), 0.35)
            try:
                before = load_comment_data(self.db_path, bvid=bvid)["metadata"]["flat_total_count"]
            except LookupError:
                before = 0

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
            save_to_sqlite(output_data, self.db_path, replace=True)
            update_progress("parse", bvid, "正在抓取弹幕")
            danmaku_result = scrape_danmaku(
                output_data["metadata"]["bvid"],
                output_data["video_raw"],
                logger=log,
            )
            if len(danmaku_result.get("items") or []) > 0:
                update_progress("parse", bvid, "弹幕抓取完成，正在保存弹幕档案")
                save_danmaku_to_sqlite(danmaku_result, self.db_path, replace=True)
            else:
                log("danmaku: got=0, skipped saving empty danmaku archive")
            payload = load_comment_data(self.db_path, bvid=output_data["metadata"]["bvid"])
            finish_progress("parse", bvid, "解析与抓取完成")
            self.send_json(
                {
                    "bvid": output_data["metadata"]["bvid"],
                    "before_count": before,
                    "scraped_count": output_data["metadata"]["flat_total_count"],
                    "after_count": payload["metadata"]["flat_total_count"],
                    "active_count": payload["metadata"].get("active_comment_count"),
                    "deleted_count": payload["metadata"].get("deleted_comment_count"),
                    "danmaku_count": len(danmaku_result.get("items") or []),
                    "video": next(
                        (
                            item
                            for item in list_video_summaries(self.db_path)
                            if item["bvid"] == output_data["metadata"]["bvid"]
                        ),
                        None,
                    ),
                    "logs": logs[-12:],
                }
            )
        except ValueError as exc:
            fail_progress("parse", bvid if "bvid" in locals() else "", str(exc))
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            fail_progress("parse", bvid if "bvid" in locals() else "", str(exc))
            self.send_json({"error": str(exc)}, status=500)
        finally:
            refresh_lock.release()

    def handle_comments_api(self, parsed):
        query = parse_qs(parsed.query)
        bvid = query.get("bvid", [None])[0]
        try:
            payload = load_comment_data(self.db_path, bvid=bvid)
        except LookupError as exc:
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json(payload)

    def handle_danmaku_api(self, parsed):
        query = parse_qs(parsed.query)
        bvid = query.get("bvid", [None])[0]
        limit = parse_optional_int(query.get("limit", [None])[0])
        try:
            payload = load_danmaku_data(self.db_path, bvid=bvid, limit=limit)
        except LookupError as exc:
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json(payload)

    def handle_refresh_api(self, parsed):
        if not refresh_lock.acquire(blocking=False):
            self.send_json({"error": "已有刷新任务正在进行，请稍后再试"}, status=409)
            return

        query = parse_qs(parsed.query)
        requested_bvid = query.get("bvid", [None])[0]
        delay = parse_float(query.get("delay", [None])[0], 0.35)
        try:
            current = load_comment_data(self.db_path, bvid=requested_bvid)
            video_ref = current["metadata"]["source_url"] or current["metadata"]["bvid"]
            before_count = current["metadata"]["flat_total_count"]
            start_progress("comments", current["metadata"]["bvid"], "正在重新抓取评论")
            logs = []
            log = make_progress_logger("comments", current["metadata"]["bvid"], logs)

            output_data = scrape_comments(
                video_ref,
                cookie_file=str(DEFAULT_COOKIE_FILE),
                delay=delay,
                logger=log,
            )
            scraped_count = output_data["metadata"]["flat_total_count"]
            update_progress("comments", current["metadata"]["bvid"], "评论抓取完成，正在保存档案")
            save_to_sqlite(output_data, self.db_path, replace=True)
            payload = load_comment_data(self.db_path, bvid=output_data["metadata"]["bvid"])
            payload["refresh"] = {
                "before_count": before_count,
                "scraped_count": scraped_count,
                "after_count": payload["metadata"]["flat_total_count"],
                "active_count": payload["metadata"].get("active_comment_count"),
                "deleted_count": payload["metadata"].get("deleted_comment_count"),
                "added_count": payload["metadata"]["flat_total_count"] - before_count,
                "logs": logs[-12:],
            }
            finish_progress("comments", output_data["metadata"]["bvid"], "评论刷新完成")
        except LookupError as exc:
            fail_progress("comments", requested_bvid or "", str(exc))
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            fail_progress("comments", requested_bvid or "", str(exc))
            self.send_json({"error": str(exc)}, status=500)
            return
        finally:
            refresh_lock.release()

        self.send_json(payload)

    def handle_danmaku_refresh_api(self, parsed):
        if not refresh_lock.acquire(blocking=False):
            self.send_json({"error": "已有抓取任务正在进行，请稍后再试"}, status=409)
            return

        query = parse_qs(parsed.query)
        requested_bvid = query.get("bvid", [None])[0]
        try:
            current = load_comment_data(self.db_path, bvid=requested_bvid)
            start_progress("danmaku", current["metadata"]["bvid"], "正在重新抓取弹幕")
            logs = []
            log = make_progress_logger("danmaku", current["metadata"]["bvid"], logs)

            before_count = load_danmaku_data(
                self.db_path,
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
            else:
                update_progress("danmaku", current["metadata"]["bvid"], "弹幕抓取完成，正在保存档案")
                save_danmaku_to_sqlite(danmaku_result, self.db_path, replace=True)
            payload = load_danmaku_data(self.db_path, bvid=current["metadata"]["bvid"], limit=None)
            payload["refresh"] = {
                "before_count": before_count,
                "after_count": payload["metadata"]["total_count"],
                "scraped_count": scraped_count,
                "logs": logs[-12:],
            }
            if warning:
                payload["refresh"]["warning"] = warning
            finish_progress("danmaku", current["metadata"]["bvid"], warning or "弹幕刷新完成")
        except LookupError as exc:
            fail_progress("danmaku", requested_bvid or "", str(exc))
            self.send_json({"error": str(exc)}, status=404)
            return
        except Exception as exc:
            fail_progress("danmaku", requested_bvid or "", str(exc))
            self.send_json({"error": str(exc)}, status=500)
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
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


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


def fail_progress(kind, bvid, message):
    now = utc_now()
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
                "stage": "失败",
                "stats": progress_state.get("stats", {}),
                "updated_at": now,
                "done": True,
                "error": message,
            }
        )


def get_progress_snapshot():
    with progress_lock:
        return {
            **progress_state,
            "logs": list(progress_state.get("logs", [])),
            "stats": dict(progress_state.get("stats", {})),
        }


def make_progress_logger(kind, bvid, logs):
    def log(message):
        logs.append(message)
        update_progress(kind, bvid, message)
        print(message, flush=True)

    return log


def progress_stage(kind, message):
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
    if "fetching children" in message or "child root" in message:
        return "抓取楼中楼"
    if "评论抓取完成" in message:
        return "保存评论"
    if kind == "parse" and "准备解析" in message:
        return "解析视频"
    return "进行中"


def progress_percent(kind, message, current=0):
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
            return max(current, min(55, 8 + page * 5))
        if "child root" in message or "fetching children" in message:
            return max(current, min(72, current + 1))
        if "正在抓取弹幕" in message:
            return max(current, 78)
        if "danmaku likes" in message:
            return max(current, min(94, current + 4))
    if kind == "comments":
        if message.startswith("main page"):
            page = parse_progress_int(message, r"main page\s+(\d+)")
            return max(current, min(65, 10 + page * 7))
        if "child root" in message or "fetching children" in message:
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
        child = re.search(r"child root=.*?unique=(\d+).*?(?:expected|count)=(\d+|None)", message)
        if child:
            stats["楼中楼已抓"] = child.group(1)
            if child.group(2) != "None":
                stats["楼中楼预期"] = child.group(2)
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
    return stats


def parse_progress_int(message, pattern):
    match = re.search(pattern, message)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def parse_float(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def parse_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


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
    args = parser.parse_args()

    handler = type(
        "ConfiguredCommentServer",
        (CommentServer,),
        {
            "db_path": Path(args.db).resolve(),
            "static_dir": Path(args.static).resolve(),
        },
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving SQLite comments app at http://{args.host}:{args.port}/")
    print(f"SQLite database: {Path(args.db).resolve()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
