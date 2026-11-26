import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from helpers import BVID

from bilibili_comment_danmaku import scraper  # noqa: E402
from database_registry import normalize_path_component  # noqa: E402
from space_archive import (  # noqa: E402
    SPACE_CACHE_MAX_AGE_SECONDS,
    cache_is_stale,
    read_space_cache,
)


def cache_payload(cached_at, items=None, partial=False):
    return {
        "mid": "42",
        "cached_at": cached_at,
        "total": len(items or []),
        "partial": partial,
        "items": items if items is not None else [{"bvid": BVID}],
    }


class SpaceCacheTests(unittest.TestCase):
    def _write(self, root, payload):
        path = Path(root) / "space_cache" / "42.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_fresh_complete_cache_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, cache_payload(datetime.now(timezone.utc).isoformat()))

            items = read_space_cache(path, "42")

            self.assertEqual(items, [{"bvid": BVID}])

    def test_expired_cache_is_ignored(self):
        stale_at = (datetime.now(timezone.utc) - timedelta(seconds=SPACE_CACHE_MAX_AGE_SECONDS + 60)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, cache_payload(stale_at))

            self.assertIsNone(read_space_cache(path, "42"))

    def test_partial_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, cache_payload(datetime.now(timezone.utc).isoformat(), partial=True))

            self.assertIsNone(read_space_cache(path, "42"))

    def test_corrupt_cache_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "space_cache" / "42.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")

            self.assertIsNone(read_space_cache(path, "42"))

    def test_missing_timestamp_counts_as_stale(self):
        self.assertTrue(cache_is_stale(""))
        self.assertTrue(cache_is_stale("not-a-date"))
        self.assertFalse(cache_is_stale(datetime.now(timezone.utc).isoformat()))


class SpaceListFetchTests(unittest.TestCase):
    """The UP video list must not be cut short silently and must honour stop requests."""

    def setUp(self):
        self._original_page = scraper.fetch_space_page if hasattr(scraper, "fetch_space_page") else None
        self._original_sleep = scraper.sleep_interruptible
        scraper.sleep_interruptible = lambda seconds, stop_checker=None: None

    def tearDown(self):
        scraper.sleep_interruptible = self._original_sleep

    def test_truncated_listing_is_cached_as_partial(self):
        import space_archive

        repeated_page = {
            "data": {
                "list": {"vlist": [{"bvid": BVID}]},
                "page": {"count": 100},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "space_cache" / "42_videos.json"
            with mock.patch.object(space_archive, "fetch_space_page", side_effect=lambda *args, **kwargs: (repeated_page, "mixin")):
                items = space_archive.fetch_space_videos("42", "", cache_path=cache_path, use_cache=False)

            self.assertEqual(len(items), 1)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertTrue(cached["partial"])
            self.assertIsNone(read_space_cache(cache_path, "42"))

    def test_stop_checker_aborts_the_listing(self):
        import space_archive

        page = {"data": {"list": {"vlist": [{"bvid": BVID}]}, "page": {"count": 100}}}
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "space_cache" / "42_videos.json"
            calls = []
            with mock.patch.object(space_archive, "fetch_space_page", side_effect=lambda *args, **kwargs: (calls.append(1), (page, "mixin"))[1]):
                with self.assertRaises(space_archive.TaskCancelled):
                    space_archive.fetch_space_videos("42", "", cache_path=cache_path, use_cache=False, stop_checker=lambda: True)

            self.assertEqual(calls, [])
            self.assertFalse(cache_path.exists())


class MainReplyLoopTests(unittest.TestCase):
    def test_empty_pages_stop_the_loop_even_with_a_live_cursor(self):
        calls = []

        def fake_signed(*_args, **_kwargs):
            calls.append(1)
            # The cursor keeps moving but every page is empty: the loop must not run forever.
            return {"data": {"replies": [], "cursor": {"next": len(calls), "is_end": False, "all_count": 100}}}

        with mock.patch.object(scraper, "request_signed_json", side_effect=fake_signed):
            with mock.patch.object(scraper, "sleep_between_pages", lambda delay, page: None):
                replies, count = scraper.fetch_main_replies("2", object(), "mixin", 0, lambda message: None)

        self.assertEqual(replies, [])
        self.assertEqual(count, 100)
        self.assertEqual(len(calls), 1)


class ChildReplyLoopTests(unittest.TestCase):
    class StubClient:
        def __init__(self, pages):
            self.pages = pages
            self.calls = 0

        def request_json(self, url, logger=None, retries=1, spacing_factor=1.0):
            page = self.pages[min(self.calls, len(self.pages) - 1)]
            self.calls += 1
            return {"data": page}

    def setUp(self):
        self._original_sleep = scraper.sleep_between_child_pages
        scraper.sleep_between_child_pages = lambda delay, page: None

    def tearDown(self):
        scraper.sleep_between_child_pages = self._original_sleep

    def test_repeated_page_does_not_loop_forever(self):
        repeated = {
            "replies": [{"rpid_str": "1"}],
            "page": {"count": 50},
        }
        client = self.StubClient([repeated])

        replies, _api_count = scraper.fetch_child_replies("2", "10", 50, client, 0, lambda message: None)

        self.assertEqual(len(replies), 1)
        self.assertLessEqual(client.calls, scraper.MAX_CHILD_PAGES_WITHOUT_GROWTH + 1)

    def test_growing_pages_are_collected_until_empty(self):
        pages = [
            {"replies": [{"rpid_str": "1"}], "page": {"count": 2}},
            {"replies": [{"rpid_str": "2"}], "page": {"count": 2}},
            {"replies": [], "page": {"count": 2}},
        ]
        client = self.StubClient(pages)

        replies, api_count = scraper.fetch_child_replies("2", "10", 2, client, 0, lambda message: None)

        self.assertEqual([item["rpid_str"] for item in replies], ["1", "2"])
        self.assertEqual(api_count, 2)


class WindowsReservedNameTests(unittest.TestCase):
    def test_reserved_device_names_are_escaped(self):
        for name in ("CON", "nul", "com1", "LPT9"):
            self.assertTrue(normalize_path_component(name).startswith("_"), name)

    def test_normal_names_are_unchanged(self):
        self.assertEqual(normalize_path_component("Owner_42"), "Owner_42")
        self.assertFalse(normalize_path_component("console").startswith("_"))
        self.assertFalse(normalize_path_component("empty").startswith("_"))

    def test_empty_name_falls_back_to_archive(self):
        self.assertEqual(normalize_path_component("***"), "archive")


if __name__ == "__main__":
    unittest.main()
