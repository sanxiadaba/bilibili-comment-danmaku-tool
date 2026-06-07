import gzip
import json
import logging
import queue
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app_logging import BoundedQueueHandler, clean_fields  # noqa: E402
from server import progress_percent, progress_stats  # noqa: E402
from bilibili_comment_danmaku.danmaku import (  # noqa: E402
    decode_response_body,
    parse_danmaku_xml,
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


BVID = "BV1xx411c7mD"


def make_comment(rpid, level, message, *, root="0", parent="0", mid="100", like=0, ctime=1700000000):
    return {
        "normalized": {
            "level": level,
            "rpid": str(rpid),
            "oid": "123",
            "type": 1,
            "mid": str(mid),
            "root": str(root),
            "parent": str(parent),
            "dialog": "0",
            "ctime": ctime,
            "time_iso": "2024-01-01T00:00:00+08:00",
            "time_iso_utc": "2023-12-31T16:00:00+00:00",
            "like": like,
            "rcount": 1 if level == 1 else 0,
            "count": 1 if level == 1 else 0,
            "state": 0,
            "attr": 0,
            "message": message,
            "ip_location": "IP属地：上海",
            "pictures": [
                {
                    "img_src": "http://i.example/a.jpg",
                    "img_width": 640,
                    "img_height": 480,
                    "img_size": 12.5,
                    "play_gif_thumbnail": False,
                }
            ]
            if level == 1
            else [],
            "emote": {
                "[doge]": {
                    "url": "http://i.example/doge.png",
                    "jump_title": "doge",
                    "meta": {"size": 1},
                    "package_id": 1,
                    "type": 1,
                }
            }
            if level == 1
            else {},
            "user": {
                "mid": str(mid),
                "uname": f"user-{mid}",
                "sex": "保密",
                "sign": "hello",
                "avatar": "http://i.example/avatar.jpg",
                "level": 5,
            },
        },
        "raw": {},
        "replies": [],
    }


def make_archive(fetched_at, comments):
    return {
        "metadata": {
            "bvid": BVID,
            "aid": 123,
            "title": "测试视频",
            "source_url": f"https://www.bilibili.com/video/{BVID}",
            "fetched_at": fetched_at,
            "sort": "like",
            "api_comment_count": len(comments),
            "top_level_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 1),
            "expected_nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "comment_total_count": len(comments),
        },
        "video_raw": {
            "cid": "456",
            "pic": "http://i.example/pic.jpg",
            "owner": {"mid": "42", "name": "UP主", "face": "http://i.example/up.jpg"},
            "stat": {"view": 1000, "danmaku": 2, "reply": 2, "favorite": 1, "coin": 2, "share": 3, "like": 4},
            "pubdate": 1700000000,
            "desc": "desc",
            "duration": 180,
        },
        "comments": comments,
    }


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


class StorageTests(unittest.TestCase):
    def test_comment_refresh_keeps_missing_comments_as_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            top = make_comment("1", 1, "top comment", mid="42", like=8)
            reply = make_comment("2", 2, "reply comment", root="1", parent="1", mid="100", like=3)
            top["replies"] = [reply]

            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", [top]), db_path, replace=True)
            refreshed_top = make_comment("1", 1, "top comment edited", mid="42", like=9)
            result = save_comments_to_sqlite(
                make_archive("2024-01-02T00:00:00+00:00", [refreshed_top]),
                db_path,
                replace=True,
            )
            loaded = load_comment_data(db_path, bvid=BVID)

            self.assertEqual(result["deleted_count"], 1)
            self.assertEqual(loaded["metadata"]["active_comment_count"], 1)
            self.assertEqual(loaded["metadata"]["deleted_comment_count"], 1)
            by_rpid = {item["normalized"]["rpid"]: item["normalized"] for item in loaded["comment_items"]}
            self.assertFalse(by_rpid["1"]["is_deleted"])
            self.assertTrue(by_rpid["2"]["is_deleted"])
            self.assertEqual(by_rpid["1"]["message"], "top comment edited")
            self.assertTrue(loaded["comments"][0]["normalized"]["is_up_owner"])

    def test_danmaku_save_load_marks_owner_and_builds_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "comment_danmaku.db"
            save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", []), db_path, replace=True)
            owner_hash = danmaku_user_hash("42")
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "100",
                            "progress": 1.2,
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000001,
                            "pool": 0,
                            "user_hash": owner_hash,
                            "weight": 9,
                            "like_count": 12,
                            "content": "owner danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "101",
                            "progress": 15.0,
                            "mode": 5,
                            "font_size": 25,
                            "color": 0xFE0302,
                            "ctime": 1700000002,
                            "pool": 0,
                            "user_hash": "other",
                            "weight": None,
                            "like_count": 2,
                            "content": "top danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        },
                    ],
                },
                db_path,
                replace=True,
            )

            loaded = load_danmaku_data(db_path, bvid=BVID, limit=1)
            summaries = list_video_summaries(db_path)

            self.assertEqual(loaded["metadata"]["total_count"], 2)
            self.assertEqual(loaded["metadata"]["limit"], 1)
            self.assertEqual(len(loaded["items"]), 1)
            self.assertTrue(loaded["items"][0]["is_up_owner"])
            self.assertEqual([bucket["bucket_start"] for bucket in loaded["buckets"]], [0, 10])
            self.assertEqual(summaries[0]["danmaku_count"], 2)


class ScraperPerformanceTests(unittest.TestCase):
    def test_child_fetch_batch_removes_serial_root_spacing(self):
        class FakeClient:
            def clone(self):
                return self

            def request_json(self, _url):
                return {
                    "data": {
                        "replies": [
                            {
                                "rpid_str": "2",
                                "oid_str": "123",
                                "type": 1,
                                "mid_str": "100",
                                "root_str": "1",
                                "parent_str": "1",
                                "dialog_str": "0",
                                "ctime": 1700000001,
                                "like": 1,
                                "rcount": 0,
                                "count": 0,
                                "state": 0,
                                "attr": 0,
                                "content": {"message": "child"},
                                "member": {"mid": "100", "uname": "user-100"},
                            }
                        ],
                        "page": {"count": 1},
                    }
                }

        main_reply = {
            "rpid_str": "1",
            "oid_str": "123",
            "type": 1,
            "mid_str": "42",
            "root_str": "0",
            "parent_str": "0",
            "dialog_str": "0",
            "ctime": 1700000000,
            "like": 8,
            "rcount": 1,
            "count": 1,
            "state": 0,
            "attr": 0,
            "content": {"message": "parent"},
            "member": {"mid": "42", "uname": "owner"},
        }
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            comments, comment_items, summary = scraper.build_threaded_output(
                [main_reply],
                "123",
                FakeClient(),
                0.35,
                lambda _message: None,
            )
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comment_items), 2)
        self.assertEqual(summary[0]["fetched_count"], 1)
        self.assertEqual(sleeps, [])

    def test_child_fetch_batch_fetches_multiple_roots_and_reports_totals(self):
        class FakeClient:
            def clone(self):
                return self

            def request_json(self, url):
                root = "1" if "root=1" in url else "3"
                child_rpid = "2" if root == "1" else "4"
                return {
                    "data": {
                        "replies": [
                            {
                                "rpid_str": child_rpid,
                                "oid_str": "123",
                                "type": 1,
                                "mid_str": "100",
                                "root_str": root,
                                "parent_str": root,
                                "dialog_str": "0",
                                "ctime": 1700000001,
                                "like": 1,
                                "rcount": 0,
                                "count": 0,
                                "state": 0,
                                "attr": 0,
                                "content": {"message": f"child {child_rpid}"},
                                "member": {"mid": "100", "uname": "user-100"},
                            }
                        ],
                        "page": {"count": 1},
                    }
                }

        replies = [
            {
                "rpid_str": "1",
                "oid_str": "123",
                "type": 1,
                "mid_str": "42",
                "root_str": "0",
                "parent_str": "0",
                "dialog_str": "0",
                "ctime": 1700000000,
                "like": 8,
                "rcount": 1,
                "count": 1,
                "state": 0,
                "attr": 0,
                "content": {"message": "parent 1"},
                "member": {"mid": "42", "uname": "owner"},
            },
            {
                "rpid_str": "3",
                "oid_str": "123",
                "type": 1,
                "mid_str": "43",
                "root_str": "0",
                "parent_str": "0",
                "dialog_str": "0",
                "ctime": 1700000002,
                "like": 7,
                "rcount": 1,
                "count": 1,
                "state": 0,
                "attr": 0,
                "content": {"message": "parent 2"},
                "member": {"mid": "43", "uname": "user-43"},
            },
        ]
        logs = []
        comments, comment_items, summary = scraper.build_threaded_output(
            replies,
            "123",
            FakeClient(),
            0,
            logs.append,
        )

        self.assertEqual(len(comments), 2)
        self.assertEqual(len(comment_items), 4)
        self.assertEqual([item["fetched_count"] for item in summary], [1, 1])
        self.assertTrue(any("fetching children batch: roots=2 workers=2" in item for item in logs))
        self.assertTrue(any("total_fetched=2 total_expected=2" in item for item in logs))

    def test_comment_page_spacing_uses_short_yields_and_periodic_full_delay(self):
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            for page in (1, 2, 20, 21):
                scraper.sleep_between_pages(0.35, page)
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(sleeps, [0.02, 0.02, 0.35, 0.02])

    def test_child_page_spacing_uses_gentler_yields_and_periodic_full_delay(self):
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            for page in (1, 2, 10, 11):
                scraper.sleep_between_child_pages(0.35, page)
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(sleeps, [0.12, 0.12, 0.35, 0.12])

    def test_signed_request_refreshes_signature_after_blocked_status(self):
        class FakeClient:
            def __init__(self):
                self.urls = []

            def request_json(self, url, retries=1):
                self.urls.append(url)
                if len(self.urls) == 1:
                    raise scraper.BilibiliRequestError("blocked", status=412, url=url)
                return {"data": {"ok": True}}

        sleeps = []
        times = iter([1000, 1030])
        original_sleep = scraper.time.sleep
        original_time = scraper.time.time
        try:
            scraper.time.sleep = sleeps.append
            scraper.time.time = lambda: next(times)
            client = FakeClient()
            result = scraper.request_signed_json(
                "https://example.test/reply",
                lambda: {"oid": 1, "next": 0},
                client,
                "0" * 32,
                lambda _message: None,
            )
        finally:
            scraper.time.sleep = original_sleep
            scraper.time.time = original_time

        self.assertEqual(result, {"data": {"ok": True}})
        self.assertEqual(sleeps, [8])
        self.assertEqual(len(client.urls), 2)
        self.assertIn("wts=1000", client.urls[0])
        self.assertIn("wts=1030", client.urls[1])
        self.assertNotEqual(client.urls[0], client.urls[1])

    def test_child_fetch_is_skipped_when_main_reply_already_has_all_children(self):
        class FailingClient:
            def request_json(self, _url):
                raise AssertionError("child API should not be called when embedded replies are complete")

        child_reply = {
            "rpid_str": "2",
            "oid_str": "123",
            "type": 1,
            "mid_str": "100",
            "root_str": "1",
            "parent_str": "1",
            "dialog_str": "0",
            "ctime": 1700000001,
            "like": 1,
            "rcount": 0,
            "count": 0,
            "state": 0,
            "attr": 0,
            "content": {"message": "embedded child"},
            "member": {"mid": "100", "uname": "user-100"},
        }
        main_reply = {
            "rpid_str": "1",
            "oid_str": "123",
            "type": 1,
            "mid_str": "42",
            "root_str": "0",
            "parent_str": "0",
            "dialog_str": "0",
            "ctime": 1700000000,
            "like": 8,
            "rcount": 1,
            "count": 1,
            "state": 0,
            "attr": 0,
            "content": {"message": "parent"},
            "member": {"mid": "42", "uname": "owner"},
            "replies": [child_reply],
        }
        sleeps = []
        original_sleep = scraper.time.sleep
        try:
            scraper.time.sleep = sleeps.append
            comments, comment_items, summary = scraper.build_threaded_output(
                [main_reply],
                "123",
                FailingClient(),
                0.35,
                lambda _message: None,
            )
        finally:
            scraper.time.sleep = original_sleep

        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comment_items), 2)
        self.assertEqual(summary[0]["fetched_count"], 1)
        self.assertEqual(sleeps, [])

    def test_child_progress_updates_stage_stats_after_main_pages(self):
        main_stats = progress_stats(
            "comments",
            "main page 109: got=17 unique=2177 all_count=9791 next=2995 is_end=False",
            {},
        )
        child_stats = progress_stats(
            "comments",
            "fetching children 12/109 root=987654 expected=34",
            main_stats,
        )
        child_percent = progress_percent("comments", "fetching children 12/109 root=987654 expected=34", 65)

        self.assertEqual(child_stats["主评论页"], "109")
        self.assertEqual(child_stats["楼中楼进度"], "12 / 109")
        self.assertEqual(child_stats["当前根评论"], "987654")
        self.assertEqual(child_stats["当前楼中楼预期"], "34")
        self.assertGreater(child_percent, 65)

    def test_child_done_progress_reports_total_child_counts(self):
        stats = progress_stats(
            "comments",
            "children done 12/109 root=987654 fetched=2 total_fetched=341 total_expected=1518",
            {},
        )
        child_percent = progress_percent(
            "comments",
            "children done 12/109 root=987654 fetched=2 total_fetched=341 total_expected=1518",
            65,
        )

        self.assertEqual(stats["楼中楼进度"], "12 / 109")
        self.assertEqual(stats["当前根评论"], "987654")
        self.assertEqual(stats["当前楼中楼已抓"], "2")
        self.assertEqual(stats["楼中楼总已抓"], "341")
        self.assertEqual(stats["楼中楼预期总数"], "1518")
        self.assertGreater(child_percent, 65)


class LoggingTests(unittest.TestCase):
    def test_clean_fields_removes_sensitive_values_and_truncates_long_strings(self):
        cleaned = clean_fields(
            {
                "token": "secret",
                "nested": {"cookie": "hidden", "safe": "visible"},
                "items": list(range(60)),
                "message": "x" * 600,
            }
        )
        self.assertNotIn("token", cleaned)
        self.assertEqual(cleaned["nested"], {"safe": "visible"})
        self.assertEqual(len(cleaned["items"]), 50)
        self.assertTrue(cleaned["message"].endswith("...[truncated]"))

    def test_bounded_queue_drops_low_priority_and_keeps_warning_when_full(self):
        log_queue = queue.Queue(maxsize=1)
        handler = BoundedQueueHandler(log_queue)
        first = logging.LogRecord("test", logging.INFO, __file__, 1, "first", (), None)
        second = logging.LogRecord("test", logging.INFO, __file__, 2, "second", (), None)
        warning = logging.LogRecord("test", logging.WARNING, __file__, 3, "warning", (), None)

        handler.emit(first)
        handler.emit(second)
        handler.emit(warning)

        self.assertEqual(log_queue.qsize(), 1)
        self.assertEqual(log_queue.get_nowait().getMessage(), "warning")


if __name__ == "__main__":
    unittest.main()
