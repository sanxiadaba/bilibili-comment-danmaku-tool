import gzip
import io
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
from http.server import BaseHTTPRequestHandler
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from helpers import BVID, make_archive, make_comment

from app_logging import BoundedQueueHandler, clean_fields  # noqa: E402
from control_api import control_capabilities, control_openapi_document, normalize_control_action_payload  # noqa: E402
from database_registry import (  # noqa: E402
    import_database_file,
    import_uploaded_database_stream,
    list_database_catalog,
    parse_multipart_files,
    resolve_database_path,
)
from errors import BadRequestError  # noqa: E402
from progress_state import progress_percent, progress_stats  # noqa: E402
from http_utils import JsonStaticRequestHandler, MAX_JSON_BODY_BYTES, parse_content_length, parse_json_object_body  # noqa: E402
from local_server import create_threading_server  # noqa: E402
from multipart_upload import parse_multipart_upload  # noqa: E402
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
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)
from bilibili_comment_danmaku.url_utils import extract_bvid  # noqa: E402
from server import (  # noqa: E402
    CommentDanmakuServer,
    ensure_importable_database_path,
    ensure_openable_local_path,
    is_local_host,
    is_local_origin,
    is_loopback_address,
    parse_archive_delete_request,
)
class RequestParsingTests(unittest.TestCase):
    def test_control_capabilities_describe_machine_callable_actions(self):
        payload = control_capabilities()

        self.assertEqual(payload["version"], "v1")
        self.assertEqual(payload["namespace"], "/api/v1/control")
        self.assertEqual(payload["openapi_endpoint"], "/api/v1/control/openapi.json")
        self.assertEqual(payload["actions"]["videos.parse"]["endpoint"], "/api/v1/control/videos/parse")
        self.assertEqual(payload["actions"]["archive.export"]["endpoint"], "/api/v1/control/archive/export")
        self.assertEqual(payload["actions"]["archive.export"]["schema"]["properties"]["format"]["enum"], ["sqlite", "json"])
        self.assertIn("format", payload["actions"]["archive.export"]["params"])
        self.assertEqual(payload["actions"]["space.tasks.control"]["endpoint"], "/api/v1/control/space/tasks/control")
        self.assertIn("action", payload["actions"]["space.tasks.control"]["params"])

    def test_control_openapi_document_includes_action_schemas(self):
        payload = control_openapi_document()
        export_schema = payload["paths"]["/api/v1/control/archive/export"]["post"]["requestBody"]["content"]["application/json"]["schema"]

        self.assertEqual(payload["openapi"], "3.1.0")
        self.assertIn("/api/v1/control/actions", payload["paths"])
        self.assertEqual(export_schema["properties"]["format"]["enum"], ["sqlite", "json"])
        task_control_schema = payload["paths"]["/api/v1/control/space/tasks/control"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(task_control_schema["properties"]["action"]["enum"], ["pause", "resume", "stop", "retry", "clear"])

    def test_control_action_payload_normalizes_params(self):
        action, params = normalize_control_action_payload(
            {"action": "archive.export", "params": {"format": "json", "bvid": BVID}}
        )

        self.assertEqual(action, "archive.export")
        self.assertEqual(params["format"], "json")
        self.assertEqual(params["bvid"], BVID)

        action, params = normalize_control_action_payload({"action": "space.tasks.control", "params": {"action": "pause"}})
        self.assertEqual(action, "space.tasks.control")
        self.assertEqual(params["action"], "pause")

    def test_control_action_payload_rejects_unknown_action(self):
        with self.assertRaises(LookupError):
            normalize_control_action_payload({"action": "unknown.action", "params": {}})

    def test_archive_delete_request_normalizes_exclusive_targets(self):
        self.assertEqual(parse_archive_delete_request({"bvid": " BV1xx411c7mD ", "bvids": ["ignored"]}), ("", ["BV1xx411c7mD"]))
        self.assertEqual(parse_archive_delete_request({"bvids": [" BV1 ", "", "BV2"]}), ("", ["BV1", "BV2"]))
        self.assertEqual(parse_archive_delete_request({"owner_mid": " 1538787344 "}), ("1538787344", []))
        with self.assertRaises(ValueError):
            parse_archive_delete_request({"owner_mid": "1538787344", "bvid": BVID})
        with self.assertRaises(ValueError):
            parse_archive_delete_request({})

    def test_parse_json_object_body_accepts_empty_or_object(self):
        self.assertEqual(parse_json_object_body(b""), {})
        self.assertEqual(parse_json_object_body(b"  "), {})
        self.assertEqual(parse_json_object_body(b'{"mid":"42"}'), {"mid": "42"})

    def test_parse_json_object_body_rejects_invalid_or_non_object_json(self):
        with self.assertRaises(BadRequestError):
            parse_json_object_body(b"{")
        with self.assertRaises(BadRequestError):
            parse_json_object_body(b"[]")
        with self.assertRaises(BadRequestError):
            parse_json_object_body("{}".encode("utf-16"))

    def test_content_length_validation_rejects_invalid_values(self):
        self.assertEqual(parse_content_length(None), 0)
        self.assertEqual(parse_content_length("12"), 12)
        with self.assertRaises(BadRequestError):
            parse_content_length("-1")
        with self.assertRaises(BadRequestError):
            parse_content_length("many")
        self.assertGreater(MAX_JSON_BODY_BYTES, 0)

    def test_streaming_multipart_parser_preserves_uploaded_file(self):
        boundary = "test-boundary"
        raw = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="archive.db"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + b"SQLite payload\x00\xff" + f"\r\n--{boundary}--\r\n".encode()
        headers = Message()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(raw))

        files = parse_multipart_upload(io.BytesIO(raw), headers, len(raw))
        try:
            self.assertEqual(files[0].filename, "archive.db")
            self.assertEqual(files[0].file.read(), b"SQLite payload\x00\xff")
        finally:
            files[0].file.close()

    def test_streaming_multipart_parser_handles_multiple_files_and_chunk_boundary(self):
        boundary = "chunk-boundary"
        first_content = b"x" * (64 * 1024 - 123) + f"\r\n--{boundary}-not-a-delimiter".encode()
        second_content = b"second\x00\xffpayload"
        raw = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="first.db"\r\n\r\n'
        ).encode() + first_content + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="second.sqlite"\r\n\r\n'
        ).encode() + second_content + f"\r\n--{boundary}--\r\n".encode()
        headers = Message()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        files = parse_multipart_upload(io.BytesIO(raw), headers, len(raw))
        try:
            self.assertEqual([item.filename for item in files], ["first.db", "second.sqlite"])
            self.assertEqual(files[0].file.read(), first_content)
            self.assertEqual(files[1].file.read(), second_content)
        finally:
            for item in files:
                item.file.close()

    def test_streaming_database_import_accepts_real_sqlite_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.db"
            database_dir = root / "databases"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), source_path, replace=True)

            with source_path.open("rb") as source:
                imported = import_uploaded_database_stream("uploaded.sqlite", source, database_dir)

            self.assertEqual(imported.name, "uploaded.sqlite")
            self.assertEqual(load_comment_data(imported, bvid=BVID)["metadata"]["bvid"], BVID)
            self.assertEqual(list(database_dir.glob(".*.upload")), [])

    def test_streaming_json_import_removes_partial_database_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"

            def fail_import(_source, target):
                Path(target).write_bytes(b"partial database")
                raise ValueError("invalid archive")

            with patch("database_registry.import_archive_json_to_sqlite", side_effect=fail_import):
                with self.assertRaisesRegex(ValueError, "invalid archive"):
                    import_uploaded_database_stream("broken.json", io.BytesIO(b"{}"), database_dir)

            self.assertEqual(list(database_dir.iterdir()), [])

    def test_static_handler_does_not_serve_same_prefix_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            static_dir = root / "dist"
            sibling = root / "dist-backup"
            static_dir.mkdir()
            sibling.mkdir()
            (static_dir / "index.html").write_bytes(b"safe index")
            (sibling / "secret.txt").write_bytes(b"secret")
            handler = object.__new__(JsonStaticRequestHandler)
            handler.static_dir = static_dir
            handler.wfile = io.BytesIO()
            handler.send_response = lambda *_args, **_kwargs: None
            handler.send_header = lambda *_args, **_kwargs: None
            handler.end_headers = lambda: None

            handler.handle_static("/../dist-backup/secret.txt")

            self.assertEqual(handler.wfile.getvalue(), b"safe index")

    def test_local_origin_and_host_validation(self):
        self.assertTrue(is_local_origin(""))
        self.assertTrue(is_local_origin("http://127.0.0.1:8000"))
        self.assertTrue(is_local_origin("http://localhost:5173"))
        self.assertFalse(is_local_origin("https://evil.example"))
        self.assertTrue(is_local_host("127.0.0.1:8000"))
        self.assertTrue(is_local_host("localhost:8000"))
        self.assertFalse(is_local_host("evil.example"))
        self.assertTrue(is_loopback_address("127.0.0.1"))
        self.assertTrue(is_loopback_address("::1"))
        self.assertFalse(is_loopback_address("192.168.1.20"))

    def test_remote_mutation_requires_explicit_token(self):
        handler = object.__new__(CommentDanmakuServer)
        handler.client_address = ("192.168.1.20", 1234)
        handler.headers = {"Host": "localhost:8001"}
        handler.allow_remote_writes = False
        handler.remote_api_token = "expected"
        responses = []
        handler.send_json = lambda payload, status=200: responses.append((payload, status))

        self.assertFalse(handler.check_mutating_request(urlparse("/api/cookie/clear")))
        self.assertEqual(responses[-1][1], 403)

        handler.allow_remote_writes = True
        handler.headers["X-Bilibili-Tool-Token"] = "expected"
        self.assertTrue(handler.check_mutating_request(urlparse("/api/cookie/clear")))

    def test_invalid_refresh_path_releases_shared_lock(self):
        import server

        handler = object.__new__(CommentDanmakuServer)
        handler.database_dir = Path(tempfile.gettempdir())
        handler.db_path = Path(tempfile.gettempdir()) / "missing.db"
        handler.request_id = "test-request"
        handler.send_json = lambda *_args, **_kwargs: None

        handler.handle_refresh_api(urlparse("/api/refresh?db_id=../outside"))
        self.assertTrue(server.refresh_lock.acquire(blocking=False))
        server.refresh_lock.release()

        handler.handle_danmaku_refresh_api(urlparse("/api/danmaku/refresh?db_id=../outside"))
        self.assertTrue(server.refresh_lock.acquire(blocking=False))
        server.refresh_lock.release()

    def test_unhandled_error_returns_json_when_response_has_not_started(self):
        handler = object.__new__(CommentDanmakuServer)
        handler.response_status = 0
        handler.request_id = "request-123"
        responses = []
        handler.send_json = lambda payload, status=200: responses.append((payload, status))

        handler.send_unhandled_error()

        self.assertEqual(responses, [({"error": "服务器内部错误", "request_id": "request-123"}, 500)])

    def test_create_threading_server_uses_next_free_port(self):
        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                return None

        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        blocked_port = blocker.getsockname()[1]
        try:
            server, actual_port = create_threading_server("127.0.0.1", blocked_port, Handler)
            try:
                self.assertGreater(actual_port, blocked_port)
            finally:
                server.server_close()
        finally:
            blocker.close()

    def test_openable_local_path_accepts_allowed_file_or_directory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "data"
            allowed.mkdir()
            exported = allowed / "archive.db"
            exported.write_text("sqlite", encoding="utf-8")
            outside = Path(tmp) / "outside"
            outside.mkdir()

            self.assertEqual(ensure_openable_local_path(exported, [allowed]), allowed.resolve())
            self.assertEqual(ensure_openable_local_path(allowed, [allowed]), allowed.resolve())
            with self.assertRaises(ValueError):
                ensure_openable_local_path(outside, [allowed])

    def test_importable_database_path_is_limited_to_allowed_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "data"
            allowed.mkdir()
            source = allowed / "archive.db"
            source.write_text("sqlite", encoding="utf-8")
            outside = Path(tmp) / "outside.db"
            outside.write_text("sqlite", encoding="utf-8")

            self.assertEqual(ensure_importable_database_path(source, [allowed]), source.resolve())
            with self.assertRaises(ValueError):
                ensure_importable_database_path(outside, [allowed])
