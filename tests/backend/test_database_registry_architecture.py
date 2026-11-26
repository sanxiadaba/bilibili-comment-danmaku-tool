import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TEST_BACKEND = ROOT / "tests" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(TEST_BACKEND) not in sys.path:
    sys.path.insert(0, str(TEST_BACKEND))

import database_registry  # noqa: E402
from helpers import BVID, make_archive, make_comment

from database_registry import (  # noqa: E402
    clear_video_summary_cache,
    database_id_for_path,
    database_info_for_path,
    export_database_path,
    find_video_database_path,
    import_database_file,
    iter_catalog_database_paths,
    list_all_video_summaries_page,
    list_database_catalog,
    normalize_path_component,
    owner_database_dir,
    owner_key,
    owner_summaries_from_videos,
    resolve_database_path,
    video_database_path,
    video_database_path_from_archive,
    video_database_sources,
    video_owner_key,
)
from errors import BadRequestError
from bilibili_comment_danmaku.storage import SCHEMA_VERSION, save_comments_to_sqlite, save_danmaku_to_sqlite


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
    def test_empty_database_file_is_reported_and_not_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            empty = database_dir / "z.db"
            empty.parent.mkdir(parents=True)
            empty.write_bytes(b"")

            catalog = list_database_catalog(root / "main.db", database_dir)

            self.assertEqual(empty.stat().st_size, 0)
            self.assertFalse(catalog[0]["ok"])
            self.assertEqual(catalog[0]["coverage_status"], "unreadable")

    def test_corrupt_database_is_reported_instead_of_disappearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            good = database_dir / "Owner_42" / f"{BVID}.db"
            good.parent.mkdir(parents=True)
            save_comments_to_sqlite(archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00"), good, replace=True)
            broken = database_dir / "Owner_42" / "BV2222222222.db"
            broken.write_bytes(b"not a database")

            page = list_all_video_summaries_page(root / "main.db", database_dir, limit=10)
            catalog = list_database_catalog(root / "main.db", database_dir)

            self.assertFalse(page["complete"])
            self.assertEqual([item["id"] for item in page["failed_databases"]], ["db:Owner_42/BV2222222222.db"])
            statuses = {item["id"]: item["ok"] for item in catalog}
            self.assertTrue(statuses[f"db:Owner_42/{BVID}.db"])
            self.assertFalse(statuses["db:Owner_42/BV2222222222.db"])

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

    def test_owner_key_is_shared_by_python_and_storage_sql(self):
        self.assertEqual(owner_key("42", "Owner"), "mid:42")
        self.assertEqual(owner_key("", ""), "name:Unknown")
        self.assertEqual(owner_key("  ", "  "), "name:Unknown")
        self.assertEqual(video_owner_key({"owner_mid": "", "owner_name": ""}), "name:Unknown")

        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp) / "databases"
            archive = archive_for(BVID, "", "", "2024-01-01T00:00:00+00:00")
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)

            from bilibili_comment_danmaku.storage import list_video_summaries_page as storage_page

            page = storage_page(db_path, limit=10, owner_key="name:Unknown")

            self.assertEqual([video["bvid"] for video in page["videos"]], [BVID])
            owners = owner_summaries_from_videos(page["videos"])
            self.assertEqual(len(owners), 1)
            self.assertEqual(owners[0]["key"], "name:Unknown")

    def test_export_directory_is_default_outside_the_scan_root(self):
        self.assertEqual(database_registry.DEFAULT_EXPORT_DIR, ROOT / "data" / "exports")

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = Path(tmp) / "exports"
            export_path = export_database_path("Owner_42", export_dir, suffix=".db")

            self.assertEqual(export_path.parent, export_dir.resolve())
            self.assertTrue(export_dir.exists())

    def test_export_copies_are_not_scanned_as_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            real_path = database_dir / "Owner_42" / f"{BVID}.db"
            export_dir = database_dir / "exports"
            export_copy = export_dir / f"{BVID}.db"
            real_path.parent.mkdir(parents=True)
            export_dir.mkdir(parents=True)
            archive = archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00")
            save_comments_to_sqlite(archive, real_path, replace=True)
            save_comments_to_sqlite(archive, export_copy, replace=True)
            newer = export_copy.stat().st_mtime + 120
            os.utime(export_copy, (newer, newer))

            with mock.patch.object(database_registry, "DEFAULT_EXPORT_DIR", export_dir):
                found = find_video_database_path(BVID, database_dir)
                paths = [db_id for _path, db_id in iter_catalog_database_paths(root / "main.db", database_dir)]
                catalog_ids = [item["id"] for item in list_database_catalog(root / "main.db", database_dir)]

            self.assertEqual(found, real_path.resolve())
            self.assertEqual(paths, [f"db:Owner_42/{BVID}.db"])
            self.assertNotIn(f"db:exports/{BVID}.db", catalog_ids)
            self.assertIn(f"db:Owner_42/{BVID}.db", catalog_ids)

    def test_import_validation_does_not_migrate_the_source_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "imports" / "Owner Archive.db"
            source.parent.mkdir(parents=True)
            archive = archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00")
            save_comments_to_sqlite(archive, source, replace=True)
            conn = sqlite3.connect(source)
            try:
                conn.execute("PRAGMA user_version = 0")
                conn.commit()
            finally:
                conn.close()
            before_bytes = source.read_bytes()
            before_mtime = source.stat().st_mtime_ns

            target = import_database_file(source, root / "databases")

            self.assertNotEqual(target.resolve(), source.resolve())
            self.assertEqual(source.read_bytes(), before_bytes)
            self.assertEqual(source.stat().st_mtime_ns, before_mtime)
            self.assertEqual(read_user_version(source), 0)
            self.assertEqual(read_user_version(target), SCHEMA_VERSION)

    def test_light_catalog_only_reads_video_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            archive = archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00")
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)

            with mock.patch.object(
                database_registry, "database_counts", side_effect=AssertionError("轻量模式不能跑全量计数")
            ), mock.patch.object(
                database_registry, "list_database_bvid_stats", side_effect=AssertionError("轻量模式不能读 bvid_stats")
            ), mock.patch.object(
                database_registry, "list_database_top_owners", side_effect=AssertionError("轻量模式不能读 top_owners")
            ), mock.patch.object(
                database_registry, "database_storage_info", side_effect=AssertionError("轻量模式不能读存储统计")
            ):
                info = database_info_for_path(db_path, root / "main.db", database_dir, include_details=False)

            self.assertTrue(info["ok"])
            self.assertEqual(info["video_count"], 1)
            self.assertEqual(info["comment_count"], 0)
            self.assertEqual(info["bvid_stats"], [])
            self.assertEqual(info["top_owners"], [])

    def test_aggregate_listing_caches_database_videos_until_the_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            archive = archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00")
            db_path = video_database_path_from_archive(archive, database_dir)
            save_comments_to_sqlite(archive, db_path, replace=True)
            clear_video_summary_cache()
            calls = []
            original = database_registry.list_video_summaries_page

            def counting_page(*args, **kwargs):
                calls.append(args)
                return original(*args, **kwargs)

            with mock.patch.object(database_registry, "list_video_summaries_page", side_effect=counting_page):
                first = list_all_video_summaries_page(root / "main.db", database_dir)
                second = list_all_video_summaries_page(root / "main.db", database_dir)

                self.assertEqual(len(calls), 1)
                self.assertEqual(first["total"], 1)
                self.assertEqual(second["videos"], first["videos"])

                newer = db_path.stat().st_mtime + 60
                os.utime(db_path, (newer, newer))
                list_all_video_summaries_page(root / "main.db", database_dir)

            self.assertEqual(len(calls), 2)

    def test_video_database_sources_scans_the_tree_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            first = archive_for("BV1111111111", "42", "Owner", "2024-01-01T00:00:00+00:00")
            second = archive_for("BV2222222222", "43", "Other", "2024-01-02T00:00:00+00:00")
            first_path = video_database_path_from_archive(first, database_dir)
            second_path = video_database_path_from_archive(second, database_dir)
            save_comments_to_sqlite(first, first_path, replace=True)
            save_comments_to_sqlite(second, second_path, replace=True)

            with mock.patch.object(database_registry, "iter_database_files", wraps=database_registry.iter_database_files) as walk:
                sources, missing = video_database_sources(
                    ["BV1111111111", "BV2222222222"], database_dir
                )

            self.assertEqual(walk.call_count, 1)
            self.assertEqual(missing, [])
            grouped = {path: sorted(group) for path, group in sources}
            self.assertEqual(
                grouped,
                {first_path.resolve(): ["BV1111111111"], second_path.resolve(): ["BV2222222222"]},
            )

    def test_file_symlink_outside_the_archive_root_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            database_dir = root / "databases"
            outside_db = Path(outside_tmp) / f"{BVID}.db"
            save_comments_to_sqlite(
                archive_for(BVID, "42", "Owner", "2024-01-01T00:00:00+00:00"), outside_db, replace=True
            )
            link_path = database_dir / "Owner_42" / f"{BVID}.db"
            link_path.parent.mkdir(parents=True)
            try:
                os.symlink(outside_db, link_path)
            except (OSError, NotImplementedError):
                self.skipTest("当前系统/权限不允许创建文件符号链接")

            self.assertEqual(list(iter_catalog_database_paths(root / "main.db", database_dir)), [])
            self.assertIsNone(find_video_database_path(BVID, database_dir))
            self.assertEqual(list_database_catalog(root / "main.db", database_dir), [])


def read_user_version(path):
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
