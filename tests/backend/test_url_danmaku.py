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
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)
from bilibili_comment_danmaku.url_utils import extract_bvid  # noqa: E402
class UrlAndDanmakuTests(unittest.TestCase):
    def test_extract_bvid_from_plain_text_and_url(self):
        self.assertEqual(extract_bvid(BVID), BVID)
        self.assertEqual(extract_bvid(f"https://www.bilibili.com/video/{BVID}/?p=1"), BVID)
        with self.assertRaises(ValueError):
            extract_bvid("not a bilibili video")

    def test_decode_response_body_supports_plain_gzip_and_deflate(self):
        payload = b"<i><d p='1,1,25,16777215,1700000000,0,hash,1'>hi</d></i>"
        self.assertEqual(decode_response_body(payload, ""), payload)
        self.assertEqual(decode_response_body(gzip.compress(payload), "gzip"), payload)
        self.assertEqual(decode_response_body(zlib.compress(payload), "deflate"), payload)

    def test_parse_danmaku_xml_skips_invalid_rows_and_unescapes_content(self):
        xml = b"""
        <i>
          <d p="12.5,1,25,16777215,1700000000,0,abc,100,9">hello &amp; hi</d>
          <d p="bad,row">skip</d>
        </i>
        """
        rows = parse_danmaku_xml(xml, BVID, "456")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dmid"], "100")
        self.assertEqual(rows[0]["progress"], 12.5)
        self.assertEqual(rows[0]["weight"], 9)
        self.assertEqual(rows[0]["content"], "hello & hi")



