"""One-time migration from the legacy single-file database to the per-video layout.

The aggregate "main" view is not a real archive any more, but older installs still keep every
video in ``data/comment_danmaku.db``. Those rows were invisible to the library, so users who
upgraded appeared to have lost their archive.
"""

from datetime import datetime, timezone
from pathlib import Path

from app_logging import log_event
from bilibili_comment_danmaku import export_archive_to_sqlite
from bilibili_comment_danmaku.storage import connect_readonly
from database_registry import find_video_database_path, video_database_path

# A target that holds less than half of the legacy rows is treated as a failed migration: an
# interrupted export leaves an empty/short database behind, and retiring the legacy file then
# destroys the only complete copy.
TARGET_MIN_ROW_RATIO = 0.5


def list_legacy_videos(db_path):
    path = Path(db_path)
    if not path.exists() or not path.is_file():
        return []
    try:
        conn = connect_readonly(path)
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT bvid, owner_mid, owner_name FROM videos ORDER BY fetched_at DESC, bvid"
        ).fetchall()
        return [
            {
                "bvid": str(row["bvid"]),
                "owner_mid": str(row["owner_mid"] or ""),
                "owner_name": str(row["owner_name"] or ""),
            }
            for row in rows
        ]
    except Exception:
        return []
    finally:
        conn.close()


def legacy_archive_row_counts(legacy_path):
    """Per-bvid comments+danmaku row counts from the legacy database (empty on any read error)."""
    try:
        conn = connect_readonly(legacy_path)
    except Exception:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT videos.bvid AS bvid,
                   (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid)
                 + (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS row_count
            FROM videos
            """
        ).fetchall()
        return {str(row["bvid"]): int(row["row_count"] or 0) for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def archive_row_count(db_path, bvid):
    """comments+danmaku rows for one video in an existing archive, or None when unreadable."""
    try:
        conn = connect_readonly(db_path)
    except Exception:
        return None
    try:
        row = conn.execute(
            """
            SELECT (SELECT COUNT(*) FROM comments WHERE bvid = ?)
                 + (SELECT COUNT(*) FROM danmaku WHERE bvid = ?) AS row_count
            """,
            (bvid, bvid),
        ).fetchone()
        return int(row["row_count"] or 0)
    except Exception:
        return None
    finally:
        conn.close()


def target_looks_incomplete(legacy_rows, target_rows):
    return bool(legacy_rows) and target_rows is not None and target_rows < legacy_rows * TARGET_MIN_ROW_RATIO


def migrate_legacy_database(legacy_path, database_dir, retire=True):
    """Copy legacy videos into ``data/databases/<owner>/<bvid>.db`` and retire the old file.

    Idempotent: videos that already exist in the per-video layout are skipped, and the legacy
    file is only renamed once every video is accounted for. An existing target that clearly has
    fewer rows than the legacy copy counts as a failure and keeps the legacy file in place.
    """
    legacy_path = Path(legacy_path).resolve()
    database_dir = Path(database_dir).resolve()
    videos = list_legacy_videos(legacy_path)
    if not videos:
        return {"migrated": 0, "skipped": 0, "failed": 0, "retired": False, "reason": ""}

    legacy_counts = legacy_archive_row_counts(legacy_path)
    migrated = 0
    skipped = 0
    failed = 0
    incomplete_bvids = []
    for video in videos:
        bvid = video["bvid"]
        existing = find_video_database_path(bvid, database_dir)
        if existing:
            legacy_rows = legacy_counts.get(bvid, 0)
            target_rows = archive_row_count(existing, bvid)
            if target_looks_incomplete(legacy_rows, target_rows):
                failed += 1
                incomplete_bvids.append(bvid)
                log_event(
                    "database.migrate_legacy.target_incomplete",
                    f"target database has {target_rows} rows but the legacy copy has {legacy_rows}; "
                    "keeping the legacy database",
                    bvid=bvid,
                    level="warning",
                )
                continue
            skipped += 1
            continue
        target = video_database_path(
            bvid,
            database_dir,
            owner_mid=video["owner_mid"],
            owner_name=video["owner_name"],
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            export_archive_to_sqlite(legacy_path, target, bvids=[bvid], archive_kind="video")
            migrated += 1
        except Exception as exc:  # noqa: BLE001 - one bad video must not abort the migration
            failed += 1
            log_event(
                "database.migrate_legacy.video_error",
                f"could not migrate legacy video: {exc}",
                bvid=bvid,
                level="warning",
            )

    retired = False
    if retire and not failed and (migrated or skipped):
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        backup = legacy_path.with_name(f"{legacy_path.name}.migrated-{stamp}")
        try:
            legacy_path.replace(backup)
            retired = True
        except OSError as exc:
            log_event(
                "database.migrate_legacy.retire_error",
                f"could not retire the legacy database: {exc}",
                level="warning",
            )

    reason = ""
    if incomplete_bvids:
        reason = (
            "目标库行数明显少于旧库（<50%），未退休旧库："
            + ", ".join(incomplete_bvids)
        )
    return {"migrated": migrated, "skipped": skipped, "failed": failed, "retired": retired, "reason": reason}
