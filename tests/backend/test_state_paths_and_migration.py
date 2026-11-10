import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import BVID, make_archive, make_comment

from bilibili_comment_danmaku import paths, scraper  # noqa: E402
from bilibili_comment_danmaku.storage import save_comments_to_sqlite  # noqa: E402
from bilibili_comment_danmaku.wbi import default_wbi_cache_path  # noqa: E402
from database_registry import find_video_database_path  # noqa: E402
from legacy_migration import list_legacy_videos, migrate_legacy_database  # noqa: E402

OTHER_BVID = "BV1other1111"


def legacy_archive(bvid, owner_mid, owner_name, comments=1):
    archive = make_archive(
        "2024-01-01T00:00:00+00:00",
        [make_comment(str(index), 1, f"comment {index}", mid="42") for index in range(comments)],
    )
    archive["metadata"] = {
        **archive["metadata"],
        "bvid": bvid,
        "aid": 123,
        "source_url": f"https://www.bilibili.com/video/{bvid}",
    }
    archive["video_raw"] = {**archive["video_raw"], "owner": {"mid": owner_mid, "name": owner_name, "face": ""}}
    return archive


class DataDirTests(unittest.TestCase):
    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {paths.DATA_DIR_ENV: "D:/custom-data"}):
            self.assertEqual(paths.default_data_dir(), Path("D:/custom-data"))

    def test_default_is_the_repo_data_dir(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(paths.DATA_DIR_ENV, None)
            self.assertEqual(paths.default_data_dir().name, "data")

    def test_publish_points_state_files_at_the_runtime_dir(self):
        with mock.patch.dict(os.environ, {}, clear=False), tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime-data"
            paths.publish_data_dir(str(runtime_dir))
            try:
                self.assertEqual(paths.state_file("x.json"), runtime_dir / "x.json")
                self.assertEqual(default_wbi_cache_path(), runtime_dir / "wbi_mixin_key.json")
                self.assertEqual(
                    scraper.default_backoff_state_path(),
                    runtime_dir / "bilibili_backoff_state.json",
                )
            finally:
                os.environ.pop(paths.DATA_DIR_ENV, None)


class LegacyMigrationTests(unittest.TestCase):
    def _seed(self, root):
        legacy = Path(root) / "comment_danmaku.db"
        save_comments_to_sqlite(legacy_archive(BVID, "42", "Owner", comments=2), legacy, replace=True)
        save_comments_to_sqlite(legacy_archive(OTHER_BVID, "43", "Other"), legacy, replace=True)
        return legacy, Path(root) / "databases"

    def test_missing_legacy_database_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = migrate_legacy_database(Path(tmp) / "comment_danmaku.db", Path(tmp) / "databases")

            self.assertEqual(result["migrated"], 0)
            self.assertFalse(result["retired"])

    def test_videos_move_into_the_per_video_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy, databases = self._seed(tmp)
            self.assertEqual(len(list_legacy_videos(legacy)), 2)

            result = migrate_legacy_database(legacy, databases)

            self.assertEqual(result["migrated"], 2)
            self.assertEqual(result["failed"], 0)
            self.assertTrue(result["retired"])
            self.assertFalse(legacy.exists())
            self.assertTrue(list(databases.glob("*.migrated-*")) == [])
            self.assertIsNotNone(find_video_database_path(BVID, databases))
            self.assertIsNotNone(find_video_database_path(OTHER_BVID, databases))
            self.assertTrue(any(legacy.parent.glob("comment_danmaku.db.migrated-*")))

    def test_already_migrated_videos_are_skipped_and_the_legacy_file_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy, databases = self._seed(tmp)
            migrate_legacy_database(legacy, databases)
            # Recreate a legacy file that only refers to already-migrated videos.
            save_comments_to_sqlite(legacy_archive(BVID, "42", "Owner"), legacy, replace=True)

            result = migrate_legacy_database(legacy, databases)

            self.assertEqual(result["migrated"], 0)
            self.assertEqual(result["skipped"], 1)
            self.assertTrue(result["retired"])

    def test_migration_can_run_without_retiring_the_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy, databases = self._seed(tmp)

            result = migrate_legacy_database(legacy, databases, retire=False)

            self.assertEqual(result["migrated"], 2)
            self.assertFalse(result["retired"])
            self.assertTrue(legacy.exists())

    def test_second_migration_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy, databases = self._seed(tmp)
            migrate_legacy_database(legacy, databases)

            again = migrate_legacy_database(legacy, databases)

            self.assertEqual(again["migrated"], 0)
            self.assertFalse(again["retired"])


if __name__ == "__main__":
    unittest.main()
