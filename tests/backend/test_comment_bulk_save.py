import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive

from bilibili_comment_danmaku import storage  # noqa: E402
from bilibili_comment_danmaku.storage import (  # noqa: E402
    _delete_comment_media_for_rpids,
    connect,
    save_comments_to_sqlite,
)

# SQLite refuses more than this many bound variables in one statement (SQLITE_LIMIT_VARIABLE_NUMBER).
SQLITE_DEFAULT_VARIABLE_LIMIT = 32766
BULK_COMMENT_COUNT = SQLITE_DEFAULT_VARIABLE_LIMIT + 734


def comment_node(index, *, picture=False, emote=False):
    normalized = {
        "level": 1,
        "rpid": str(index),
        "oid": "123",
        "type": 1,
        "mid": "42",
        "root": "0",
        "parent": "0",
        "dialog": "0",
        "ctime": 1700000000 + index,
        "time_iso": "",
        "time_iso_utc": "",
        "like": 0,
        "rcount": 0,
        "count": 0,
        "state": 0,
        "attr": 0,
        "message": f"comment {index}",
        "ip_location": "",
        "pictures": [
            {
                "img_src": f"http://i.example/{index}.jpg",
                "img_width": 640,
                "img_height": 480,
                "img_size": 12.5,
                "play_gif_thumbnail": False,
            }
        ]
        if picture
        else [],
        "emote": {
            "[doge]": {
                "url": f"http://i.example/doge-{index}.png",
                "jump_title": "doge",
                "meta": {"size": 1},
                "package_id": 1,
                "type": 1,
            }
        }
        if emote
        else {},
        "user": {"mid": "42", "uname": "user-42", "sex": "unknown", "sign": "", "avatar": "", "level": 5},
    }
    return {"normalized": normalized, "raw": {}, "replies": []}


def bulk_archive(count, *, pictures=False, emotes=False):
    comments = [comment_node(index, picture=pictures, emote=emotes) for index in range(count)]
    return make_archive("2024-01-01T00:00:00+00:00", comments)


class BulkCommentSaveTests(unittest.TestCase):
    def test_saves_more_comments_than_the_sqlite_variable_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bulk.db"
            archive = bulk_archive(BULK_COMMENT_COUNT, pictures=True, emotes=True)

            result = save_comments_to_sqlite(archive, db_path, replace=True)

            self.assertEqual(result["total_count"], BULK_COMMENT_COUNT)
            conn = connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], BULK_COMMENT_COUNT)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comment_pictures").fetchone()[0], BULK_COMMENT_COUNT)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comment_emotes").fetchone()[0], BULK_COMMENT_COUNT)
            finally:
                conn.close()

    def test_saving_twice_keeps_media_in_sync_without_duplicating(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sync.db"
            first = bulk_archive(2500, pictures=True, emotes=True)
            save_comments_to_sqlite(first, db_path, replace=True)

            second = bulk_archive(2500, pictures=False, emotes=False)
            save_comments_to_sqlite(second, db_path, replace=True)

            conn = connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2500)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comment_pictures").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comment_emotes").fetchone()[0], 0)
            finally:
                conn.close()


class BatchedMediaCleanupTests(unittest.TestCase):
    def test_handles_far_more_rpids_than_one_statement_allows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "media.db"
            conn = connect(db_path)
            try:
                storage.ensure_schema(conn)
                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
                rpids = [str(index) for index in range(70000)]
                conn.executemany(
                    "INSERT INTO comment_pictures (rpid, img_src) VALUES (?, ?)",
                    [(rpid, f"http://i.example/{rpid}.jpg") for rpid in rpids],
                )
                conn.commit()

                _delete_comment_media_for_rpids(conn, rpids)

                self.assertEqual(conn.execute("SELECT COUNT(*) FROM comment_pictures").fetchone()[0], 0)
            finally:
                conn.close()

    def test_deletes_only_the_listed_rpids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "media.db"
            conn = connect(db_path)
            try:
                storage.ensure_schema(conn)
                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.executemany(
                    "INSERT INTO comment_pictures (rpid, img_src) VALUES (?, ?)",
                    [("1", "http://i.example/1.jpg"), ("2", "http://i.example/2.jpg"), ("3", "http://i.example/3.jpg")],
                )
                conn.commit()

                _delete_comment_media_for_rpids(conn, ["1", "3", "3"])

                remaining = [row["rpid"] for row in conn.execute("SELECT rpid FROM comment_pictures").fetchall()]
                self.assertEqual(remaining, ["2"])
            finally:
                conn.close()

    def test_save_comments_routes_media_cleanup_through_the_batched_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "archive.db"
            archive = bulk_archive(3, pictures=True, emotes=True)
            with mock.patch.object(
                storage,
                "_delete_comment_media_for_rpids",
                wraps=storage._delete_comment_media_for_rpids,
            ) as cleanup:
                save_comments_to_sqlite(archive, db_path, replace=True)

            cleanup.assert_called_once()
            self.assertEqual(cleanup.call_args[0][1], ["0", "1", "2"])


if __name__ == "__main__":
    unittest.main()
