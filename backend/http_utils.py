import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from app_logging import log_event, log_exception, new_request_id
from database_registry import resolve_database_path
from errors import BadRequestError


class JsonStaticRequestHandler(BaseHTTPRequestHandler):
    db_path = None
    static_dir = None
    database_dir = None

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

    def handle_static(self, path):
        relative = path.lstrip("/")
        static_root = self.static_dir.resolve()
        file_path = (self.static_dir / relative).resolve()
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


def first_query_int(query, key, default):
    try:
        return int(query.get(key, [default])[0])
    except (TypeError, ValueError):
        return default


def parse_optional_int(value):
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
