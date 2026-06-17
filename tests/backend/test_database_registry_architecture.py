import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TEST_BACKEND = ROOT / "tests" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(TEST_BACKEND) not in sys.path:
    sys.path.insert(0, str(TEST_BACKEND))

from helpers import BVID, make_archive, make_comment

from database_registry import (
    database_id_for_path,
    find_video_database_path,
    iter_catalog_database_paths,
    list_all_video_summaries_page,
    list_database_catalog,
    normalize_path_component,
    owner_database_dir,
    resolve_database_path,
    video_database_path,
    video_database_path_from_archive,
)
from errors import BadRequestError
from bilibili_comment_danmaku.storage import save_comments_to_sqlite, save_danmaku_to_sqlite


def archive_for(bvid, owner_mid, owner_name, fetched_at, comments=None):
    archive = make_archive(fetched_at, comments if comments is not None else [make_comment(f"{bvid}-1", 1, "comment")])
    archive["metadata"] = {
        **archive["metadata"],
        "bvid": bvid,
        "aid": sum(ord(char) for char in bvid),
        "source_url": f"https://www.bilibili.com/video/{bvid}",
    }
    archive["video_raw"] = {
        **archive["video_raw"],
        "owner": {"mid": str(owner_mid), "name": owner_name, "face": ""},
    }
    return archive


class DatabaseRegistryArchitectureTests(unittest.TestCase):
    def test_catalog_does_not_list_legacy_main_database_even_when_it_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            database_dir = root / "databases"
            save_comments_to_sqlite(archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00"), main_db, replace=True)

            catalog = list_database_catalog(main_db, database_dir)
            paths = list(iter_catalog_database_paths(main_db, database_dir))

            self.assertEqual(catalog, [])
            self.assertEqual(paths, [])

    def test_aggregate_listing_works_without_main_database_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_db = root / "comment_danmaku.db"
            database_dir = root / "databases"
            first = archive_for("BV1111111111", "42", "Owner", "2024-01-01T00:00:00+00:00")
            second = archive_for("BV2222222222", "42", "Owner", "2024-01-02T00:00:00+00:00")
            save_comments_to_sqlite(first, video_database_path_from_archive(first, database_dir), replace=True)
            save_comments_to_sqlite(second, video_database_path_from_archive(second, database_dir), replace=True)

            page = list_all_video_summaries_page(main_db, database_dir, limit=1, offset=0)

            self.assertFalse(main_db.exists())
            self.assertEqual(page["total"], 2)
            self.assertEqual(page["limit"], 1)
            self.assertTrue(page["has_more"])
            self.assertEqual(page["videos"][0]["bvid"], "BV2222222222")
            self.assertEqual(page["videos"][0]["db_id"], "db:Owner_42/BV2222222222.db")
            self.assertEqual(page["owners"][0]["owner_mid"], "42")
            self.assertEqual(page["owners"][0]["video_count"], 2)

    def test_video_path_uses_sanitized_owner_folder_and_bvid_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"

            owner_dir = owner_database_dir("1538787344", "UP / name:with*bad?chars", database_dir)
            path = video_database_path("BV1xx411c7mD", database_dir, owner_mid="1538787344", owner_name="UP / name:with*bad?chars")

            self.assertEqual(owner_dir.name, "UP_name_with_bad_chars_1538787344")
            self.assertEqual(path, database_dir.resolve() / "UP_name_with_bad_chars_1538787344" / "BV1xx411c7mD.db")
            self.assertTrue(owner_dir.exists())

    def test_video_path_from_archive_falls_back_to_metadata_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = archive_for(BVID, "", "", "2024-01-01T00:00:00+00:00")
            archive["video_raw"] = {}
            archive["metadata"]["owner_mid"] = "1538787344"
            archive["metadata"]["owner_name"] = "Fallback Owner"

            path = video_database_path_from_archive(archive, Path(tmp) / "databases")

            self.assertEqual(path.parent.name, "Fallback_Owner_1538787344")
            self.assertEqual(path.name, f"{BVID}.db")

    def test_find_video_database_path_prefers_newest_duplicate_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            old_path = database_dir / "Owner_42" / f"{BVID}.db"
            new_path = database_dir / "Owner_42_copy" / f"{BVID}.db"
            old_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            save_comments_to_sqlite(archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00"), old_path, replace=True)
            save_comments_to_sqlite(archive_for(BVID, "42", "Owner", "2024-01-02T00:00:00+00:00"), new_path, replace=True)
            old_mtime = old_path.stat().st_mtime
            newer_mtime = old_mtime + 60
            new_path.touch()
            import os

            os.utime(new_path, (newer_mtime, newer_mtime))

            self.assertEqual(find_video_database_path(BVID, database_dir), new_path.resolve())

    def test_aggregate_deduplicates_bvid_and_prefers_richer_hotplug_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            smaller = database_dir / "Owner_42" / f"{BVID}.db"
            richer = database_dir / "Owner_42_richer" / f"{BVID}.db"
            smaller.parent.mkdir(parents=True, exist_ok=True)
            richer.parent.mkdir(parents=True, exist_ok=True)
            save_comments_to_sqlite(archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00", [make_comment("1", 1, "one")]), smaller, replace=True)
            rich_archive = archive_for(
                BVID,
                "42",
                "Owner",
                "2024-01-01T00:00:00+00:00",
                [make_comment("1", 1, "one"), make_comment("2", 1, "two")],
            )
            save_comments_to_sqlite(rich_archive, richer, replace=True)
            save_danmaku_to_sqlite(
                {
                    "bvid": BVID,
                    "cid": "456",
                    "items": [
                        {
                            "bvid": BVID,
                            "cid": "456",
                            "dmid": "dm-1",
                            "progress": 1.0,
                            "mode": 1,
                            "font_size": 25,
                            "color": 0xFFFFFF,
                            "ctime": 1700000000,
                            "pool": 0,
                            "user_hash": "hash",
                            "weight": 1,
                            "like_count": 0,
                            "content": "danmaku",
                            "fetched_at": "2024-01-01T00:00:00+00:00",
                        }
                    ],
                },
                richer,
                replace=True,
            )

            page = list_all_video_summaries_page(root / "comment_danmaku.db", database_dir)

            self.assertEqual(page["total"], 1)
            self.assertEqual(page["videos"][0]["db_id"], f"db:Owner_42_richer/{BVID}.db")
            self.assertEqual(page["videos"][0]["comment_total_count"], 2)
            self.assertEqual(page["videos"][0]["danmaku_count"], 1)

    def test_database_ids_are_relative_to_hotplug_root_and_reject_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            archive = archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00")
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)

            db_id = database_id_for_path(db_path, root / "comment_danmaku.db", database_dir)

            self.assertEqual(db_id, f"db:Owner_42/{BVID}.db")
            self.assertEqual(resolve_database_path(db_id, root / "comment_danmaku.db", database_dir), db_path.resolve())
            with self.assertRaises(BadRequestError):
                resolve_database_path("db:Owner_42/../../escape.db", root / "comment_danmaku.db", database_dir)

    def test_normalize_path_component_keeps_unicode_and_bounds_length(self):
        raw = "测试 UP / 1538787344 " + ("x" * 200)

        normalized = normalize_path_component(raw)

        self.assertTrue(normalized.startswith("测试_UP_1538787344_"))
        self.assertLessEqual(len(normalized), 100)
        self.assertNotIn("/", normalized)


if __name__ == "__main__":
    unittest.main()
