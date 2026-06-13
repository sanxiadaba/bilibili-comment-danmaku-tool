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
from server import parse_json_object_body  # noqa: E402
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
    list_video_summaries,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)
from bilibili_comment_danmaku.url_utils import extract_bvid  # noqa: E402
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


