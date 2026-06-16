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
from http_utils import MAX_JSON_BODY_BYTES, parse_content_length, parse_json_object_body  # noqa: E402
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
from server import ensure_importable_database_path, ensure_openable_local_path, is_local_host, is_local_origin  # noqa: E402
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

    def test_local_origin_and_host_validation(self):
        self.assertTrue(is_local_origin(""))
        self.assertTrue(is_local_origin("http://127.0.0.1:8000"))
        self.assertTrue(is_local_origin("http://localhost:5173"))
        self.assertFalse(is_local_origin("https://evil.example"))
        self.assertTrue(is_local_host("127.0.0.1:8000"))
        self.assertTrue(is_local_host("localhost:8000"))
        self.assertFalse(is_local_host("evil.example"))

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
