import tempfile
import unittest
from pathlib import Path

from helpers import BVID, make_archive, make_comment

from bilibili_comment_danmaku import load_comment_data, save_comments_to_sqlite  # noqa: E402


def thread(root_id, reply_ids=(), ctime=1700000000):
    node = make_comment(str(root_id), 1, f"root {root_id}", mid="42", ctime=ctime)
    node["replies"] = [
        make_comment(
            str(reply_id),
            2,
            f"reply {reply_id}",
            mid="43",
            root=str(root_id),
            parent=str(root_id),
            ctime=ctime + index + 1,
        )
        for index, reply_id in enumerate(reply_ids)
    ]
    return node


def build_db(root):
    db_path = Path(root) / "archive.db"
    threads = [
        thread(1, [11, 12], ctime=1700000001),
        thread(2, [21], ctime=1700000002),
        thread(3, [], ctime=1700000003),
    ]
    save_comments_to_sqlite(make_archive("2024-01-01T00:00:00+00:00", threads), db_path, replace=True)
    return db_path


class RootPaginationTests(unittest.TestCase):
    def test_a_page_is_counted_in_threads_and_keeps_their_replies(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = build_db(tmp)

            page = load_comment_data(db_path, bvid=BVID, limit=1, offset=0)

            self.assertEqual([node["normalized"]["rpid"] for node in page["comments"]], ["1"])
            self.assertEqual([reply["normalized"]["rpid"] for reply in page["comments"][0]["replies"]], ["11", "12"])
            self.assertEqual({node["normalized"]["rpid"] for node in page["comment_items"]}, {"1", "11", "12"})
            self.assertTrue(page["metadata"]["has_more"])

    def test_second_page_continues_after_the_last_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = build_db(tmp)

            page = load_comment_data(db_path, bvid=BVID, limit=2, offset=2)

            self.assertEqual([node["normalized"]["rpid"] for node in page["comments"]], ["3"])
            self.assertFalse(page["metadata"]["has_more"])

    def test_replies_from_other_pages_are_not_leaked_into_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = build_db(tmp)

            page = load_comment_data(db_path, bvid=BVID, limit=1, offset=1)

            rpids = {node["normalized"]["rpid"] for node in page["comment_items"]}
            self.assertEqual(rpids, {"2", "21"})
            self.assertNotIn("11", rpids)

    def test_full_load_still_returns_every_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = build_db(tmp)

            payload = load_comment_data(db_path, bvid=BVID)

            self.assertEqual(len(payload["comment_items"]), 6)
            self.assertFalse(payload["metadata"]["has_more"])

    def test_offset_past_the_end_returns_an_empty_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = build_db(tmp)

            page = load_comment_data(db_path, bvid=BVID, limit=10, offset=50)

            self.assertEqual(page["comments"], [])
            self.assertEqual(page["comment_items"], [])
            self.assertFalse(page["metadata"]["has_more"])


if __name__ == "__main__":
    unittest.main()
