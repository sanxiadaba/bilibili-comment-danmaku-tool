"""归档导入导出：SQLite / JSON。"""

import json
import os
import time
import uuid
from pathlib import Path

from .archive_manifest import (
    build_archive_manifest,
    fetch_manifest_video_rows,
    manifest_from_video_rows,
    read_archive_meta,
    write_archive_meta,
)
from .archive_sqlite import copy_table_query, remove_sqlite_file_with_sidecars
from .storage import (
    connect,
    connect_readonly,
    ensure_schema,
    ensure_schema_if_needed,
    load_comment_data,
    load_danmaku_data,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
    schema_is_current,
)

JSON_ARCHIVE_FORMAT = "bilibili-comment-danmaku-json-data"
JSON_ARCHIVE_SCHEMA_VERSION = 2


def require_source_database(source_path):
    """Resolve an export source and refuse missing files.

    ``connect()`` happily creates a brand-new empty database for a path that does not exist, so a
    stale catalog entry used to turn a failed export into an empty archive file.
    """
    path = Path(source_path).resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"源数据库不存在：{path}")
    return path


def open_export_source(source_path):
    """Open a source archive for reading without migrating it.

    Exports used to run the full ``ensure_schema`` on every source, which takes a write lock and
    can spend seconds migrating an old file just to copy rows out. Current files are read through
    a read-only handle; only a genuinely older file falls back to a writable migration.
    """
    path = require_source_database(source_path)
    try:
        conn = connect_readonly(path)
    except Exception:
        conn = None
    if conn is not None:
        if schema_is_current(conn):
            return conn
        conn.close()
    conn = connect(path)
    try:
        if ensure_schema_if_needed(conn):
            conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def _temporary_sibling(target_path, purpose):
    target_path = Path(target_path)
    return target_path.with_name(f".{target_path.name}.{purpose}-{os.getpid()}-{uuid.uuid4().hex[:8]}")


def replace_file(temp_path, target_path, attempts=20):
    """Swap a staged file into place, retrying the transient Windows file-busy errors.

    A task worker (or Windows Defender) can hold the target for a moment; five tries of <1s total
    used to surface as a 500 on an otherwise fine import.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            os.replace(temp_path, target_path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    raise last_error


def remove_wal_sidecars(path):
    path = Path(path)
    for candidate in (
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
        # A hot rollback journal left by a crash would be replayed into the newly imported file.
        path.with_name(f"{path.name}-journal"),
    ):
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass


def _video_payload(source_path, bvid):
    comments = load_comment_data(source_path, bvid=bvid)
    danmaku = load_danmaku_data(source_path, bvid=bvid, limit=None)
    return {
        "bvid": bvid,
        "metadata": comments.get("metadata") or {},
        "video_raw": comments.get("video_raw") or {},
        "comments": comments.get("comments") or [],
        "comment_items": comments.get("comment_items") or [],
        "danmaku": danmaku,
    }


def write_json_archive(target_path, manifest, videos):
    """Stream the archive JSON into a temp file and swap it in only once it is complete.

    The old implementation built every comment in memory and then a second giant string via
    ``json.dumps(indent=2)``. The payload format is unchanged (same keys, same ``format`` value);
    only the pretty-printing is gone so large archives stay flat in memory.
    """
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling(target_path, "json")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write('{"format": ')
            json.dump(JSON_ARCHIVE_FORMAT, handle, ensure_ascii=False)
            handle.write(', "schema_version": ')
            json.dump(JSON_ARCHIVE_SCHEMA_VERSION, handle, ensure_ascii=False)
            handle.write(', "manifest": ')
            json.dump(manifest, handle, ensure_ascii=False)
            handle.write(', "videos": [')
            first = True
            for video in videos:
                if not first:
                    handle.write(", ")
                json.dump(video, handle, ensure_ascii=False)
                first = False
            handle.write("]}")
        replace_file(temp_path, target_path)
    except Exception:
        remove_sqlite_file_with_sidecars(temp_path)
        raise


def checkpoint_for_handoff(conn):
    """Make a staged SQLite file self-contained before it is renamed into place."""
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.commit()


def export_archive_to_sqlite(
    db_path,
    target_path,
    *,
    bvids=None,
    owner_mid=None,
    archive_kind=None,
    label="",
    owner_name="",
):
    selected_bvids = [str(value).strip() for value in (bvids or []) if str(value).strip()]
    owner_mid = str(owner_mid or "").strip()
    if bool(selected_bvids) == bool(owner_mid):
        raise ValueError("必须指定 owner_mid 或 bvids 之一")

    source_path = require_source_database(db_path)
    target_path = Path(target_path).resolve()
    if target_path == source_path:
        raise ValueError("导出目标不能覆盖当前主数据库")

    source = open_export_source(source_path)
    target = None
    try:
        # Resolve the selection before touching the target so a bad request cannot leave an
        # empty archive behind in the catalog.
        selected_bvids = select_export_bvids(source, bvids=selected_bvids or None, owner_mid=owner_mid or None)
        _stage_source_bvids(source, selected_bvids)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        remove_sqlite_file_with_sidecars(target_path)
        target = connect(target_path)
        ensure_schema(target)

        counts = {
            "videos": copy_table_query(source, target, "videos", "bvid IN (SELECT bvid FROM export_bvids)"),
            "users": copy_table_query(
                source,
                target,
                "users",
                """
                mid IN (
                    SELECT DISTINCT mid
                    FROM comments
                    WHERE bvid IN (SELECT bvid FROM export_bvids)
                      AND mid IS NOT NULL
                      AND mid <> ''
                )
                """,
            ),
            "comments": copy_table_query(source, target, "comments", "bvid IN (SELECT bvid FROM export_bvids)"),
            "comment_pictures": copy_table_query(
                source,
                target,
                "comment_pictures",
                "rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))",
            ),
            "comment_emotes": copy_table_query(
                source,
                target,
                "comment_emotes",
                "rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))",
            ),
            "danmaku": copy_table_query(source, target, "danmaku", "bvid IN (SELECT bvid FROM export_bvids)"),
        }
        manifest = build_archive_manifest(
            source,
            selected_bvids,
            counts,
            archive_kind=archive_kind,
            label=label,
            owner_mid=owner_mid,
            owner_name=owner_name,
            source_path=source_path,
            target_path=target_path,
        )
        write_archive_meta(target, manifest)
        checkpoint_for_handoff(target)
        return {
            "path": str(target_path),
            "json_path": "",
            "bvids": selected_bvids,
            "counts": counts,
            "manifest": manifest,
            "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
        }
    except Exception:
        if target is not None:
            target.close()
            target = None
        remove_sqlite_file_with_sidecars(target_path)
        raise
    finally:
        source.close()
        if target is not None:
            target.close()


MERGED_EXPORT_TABLES = (
    ("videos", "videos", "bvid IN (SELECT bvid FROM export_bvids)"),
    (
        "users",
        "users",
        """
        mid IN (
            SELECT DISTINCT mid
            FROM comments
            WHERE bvid IN (SELECT bvid FROM export_bvids)
              AND mid IS NOT NULL
              AND mid <> ''
        )
        """,
    ),
    ("comments", "comments", "bvid IN (SELECT bvid FROM export_bvids)"),
    (
        "comment_pictures",
        "comment_pictures",
        "rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))",
    ),
    (
        "comment_emotes",
        "comment_emotes",
        "rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))",
    ),
    ("danmaku", "danmaku", "bvid IN (SELECT bvid FROM export_bvids)"),
)


def export_archive_from_databases(
    sources,
    target_path,
    *,
    archive_kind=None,
    label="",
    owner_mid="",
    owner_name="",
    export_format="sqlite",
):
    """Export videos that live in separate per-video databases into one archive.

    ``sources`` is an iterable of ``(db_path, bvids)`` pairs. Each source contributes only the
    listed videos, so the aggregate "main" view can export an owner or a selection without
    touching the legacy single-file database. Entries are merged per path first: two chunks for
    the same database used to leave the second chunk out of ``videos`` while its bvids stayed in
    the manifest.
    """
    merged = {}
    missing = []
    for source_path, source_bvids in sources or []:
        bvids = [str(value).strip() for value in (source_bvids or []) if str(value).strip()]
        if not bvids or not source_path:
            continue
        path = Path(source_path).resolve()
        if not path.exists() or not path.is_file():
            if path not in missing:
                missing.append(path)
            continue
        bucket = merged.setdefault(path, [])
        for bvid in bvids:
            if bvid not in bucket:
                bucket.append(bvid)
    if not merged:
        if missing:
            raise ValueError(f"源数据库不存在：{'; '.join(str(path) for path in missing)}")
        raise LookupError("没有可导出的本地视频档案")

    fmt = str(export_format or "sqlite").strip().lower()
    if fmt not in {"sqlite", "json"}:
        raise ValueError("导出格式只支持 sqlite 或 json")
    options = {
        "archive_kind": archive_kind,
        "label": label,
        "owner_mid": owner_mid,
        "owner_name": owner_name,
    }
    normalized = list(merged.items())
    if fmt == "json":
        result = _export_databases_to_json(normalized, target_path, **options)
    else:
        result = _export_databases_to_sqlite(normalized, target_path, **options)
    result["skipped"] = [str(path) for path in missing]
    return result


def _stage_source_bvids(source, bvids):
    source.execute("DROP TABLE IF EXISTS export_bvids")
    source.execute("CREATE TEMP TABLE export_bvids (bvid TEXT PRIMARY KEY)")
    source.executemany("INSERT OR IGNORE INTO export_bvids (bvid) VALUES (?)", [(bvid,) for bvid in bvids])


def _merged_source_counts(source):
    counts = {}
    for key, table, where_sql in MERGED_EXPORT_TABLES:
        counts[key] = source.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}").fetchone()[0]
    return counts


def _export_databases_to_sqlite(normalized, target_path, *, archive_kind=None, label="", owner_mid="", owner_name=""):
    target_path = Path(target_path).resolve()
    for source_path, _source_bvids in normalized:
        if source_path == target_path:
            raise ValueError("导出目标不能覆盖源数据库")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    remove_sqlite_file_with_sidecars(target_path)

    counts = {key: 0 for key, _table, _where in MERGED_EXPORT_TABLES}
    video_rows = []
    selected_bvids = []
    source_paths = []
    target = connect(target_path)
    try:
        ensure_schema(target)
        for source_path, source_bvids in normalized:
            source_paths.append(source_path)
            source = open_export_source(source_path)
            try:
                _stage_source_bvids(source, source_bvids)
                for key, table, where_sql in MERGED_EXPORT_TABLES:
                    counts[key] += copy_table_query(source, target, table, where_sql)
                video_rows.extend(fetch_manifest_video_rows(source))
                for bvid in source_bvids:
                    if bvid not in selected_bvids:
                        selected_bvids.append(bvid)
            finally:
                source.close()

        manifest = manifest_from_video_rows(
            video_rows,
            selected_bvids,
            counts,
            archive_kind=archive_kind,
            label=label,
            owner_mid=owner_mid,
            owner_name=owner_name,
            source_path=";".join(str(path) for path in source_paths),
            target_path=target_path,
        )
        write_archive_meta(target, manifest)
        checkpoint_for_handoff(target)
        return {
            "path": str(target_path),
            "json_path": "",
            "bvids": selected_bvids,
            "counts": counts,
            "manifest": manifest,
            "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
        }
    except Exception:
        target.close()
        remove_sqlite_file_with_sidecars(target_path)
        raise
    finally:
        target.close()


def _export_databases_to_json(normalized, target_path, *, archive_kind=None, label="", owner_mid="", owner_name=""):
    target_path = Path(target_path).resolve()
    for source_path, _source_bvids in normalized:
        if source_path == target_path:
            raise ValueError("导出目标不能覆盖源数据库")

    counts = {key: 0 for key, _table, _where in MERGED_EXPORT_TABLES}
    video_rows = []
    selected_bvids = []
    source_paths = []
    bvid_sources = {}
    for source_path, source_bvids in normalized:
        source_paths.append(source_path)
        source = open_export_source(source_path)
        try:
            _stage_source_bvids(source, source_bvids)
            for key, values in _merged_source_counts(source).items():
                counts[key] += values
            video_rows.extend(fetch_manifest_video_rows(source))
        finally:
            source.close()
        for bvid in source_bvids:
            if bvid in selected_bvids:
                continue
            selected_bvids.append(bvid)
            bvid_sources[bvid] = source_path

    manifest = manifest_from_video_rows(
        video_rows,
        selected_bvids,
        counts,
        archive_kind=archive_kind,
        label=label,
        owner_mid=owner_mid,
        owner_name=owner_name,
        source_path=";".join(str(path) for path in source_paths),
        target_path=target_path,
    )
    write_json_archive(
        target_path,
        manifest,
        (_video_payload(bvid_sources[bvid], bvid) for bvid in selected_bvids),
    )
    return {
        "path": str(target_path),
        "json_path": str(target_path),
        "bvids": selected_bvids,
        "counts": counts,
        "manifest": manifest,
        "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
    }


def export_archive_to_json(
    db_path,
    target_path,
    *,
    bvids=None,
    owner_mid=None,
    archive_kind=None,
    label="",
    owner_name="",
):
    source_path = require_source_database(db_path)
    target_path = Path(target_path).resolve()
    if target_path == source_path:
        raise ValueError("导出目标不能覆盖当前主数据库")

    source = open_export_source(source_path)
    try:
        selected_bvids = select_export_bvids(source, bvids=bvids, owner_mid=owner_mid)
        _stage_source_bvids(source, selected_bvids)
        counts = export_counts(source)
        manifest = build_archive_manifest(
            source,
            selected_bvids,
            counts,
            archive_kind=archive_kind,
            label=label,
            owner_mid=owner_mid,
            owner_name=owner_name,
            source_path=source_path,
            target_path=target_path,
        )
    finally:
        source.close()

    write_json_archive(
        target_path,
        manifest,
        (_video_payload(source_path, bvid) for bvid in selected_bvids),
    )
    return {
        "path": str(target_path),
        "json_path": str(target_path),
        "bvids": selected_bvids,
        "counts": counts,
        "manifest": manifest,
        "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
    }


def import_archive_json_to_sqlite(source_path, target_path):
    source_path = Path(source_path).resolve()
    target_path = Path(target_path).resolve()
    try:
        # json.load parses from the handle instead of building a second full copy as a string;
        # the object itself still has to fit in memory, so SQLite export stays the default for
        # very large archives.
        with source_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON 归档格式不正确") from exc
    if not isinstance(payload, dict) or payload.get("format") not in {
        "bilibili-comment-danmaku-json-data",
        "bilibili-comment-danmaku-json-archive",
    }:
        raise ValueError("不是可导入的 Bilibili JSON 归档")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        raise ValueError("JSON 归档中没有视频数据")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Import into a hidden sibling first: a bad item halfway through the archive used to leave a
    # truncated database sitting at the real target path, which then blocked a retry.
    temp_path = _temporary_sibling(target_path, "import")
    try:
        for item in videos:
            if not isinstance(item, dict):
                raise ValueError("JSON 归档中的视频数据不完整")
            if isinstance(item.get("comments"), dict):
                comments = item["comments"]
            else:
                comments = {
                    "metadata": item.get("metadata") or {},
                    "video_raw": item.get("video_raw") or {},
                    "comments": item.get("comments") or [],
                    "comment_items": item.get("comment_items") or [],
                }
            if not isinstance(comments.get("metadata"), dict) or not isinstance(comments.get("video_raw"), dict):
                raise ValueError("JSON 归档中的视频数据不完整")
            required_metadata = ("bvid", "fetched_at", "title", "aid", "source_url")
            missing_keys = [key for key in required_metadata if not (comments.get("metadata") or {}).get(key)]
            if missing_keys:
                raise ValueError(f"JSON 归档中的视频数据不完整（缺少 {', '.join(missing_keys)}）")
            save_comments_to_sqlite(comments, temp_path, replace=True)
            danmaku = item.get("danmaku")
            if isinstance(danmaku, dict):
                # A malformed archive may miss keys entirely; report it as a bad archive instead
                # of letting KeyError surface as a 500.
                metadata = danmaku.get("metadata") if isinstance(danmaku.get("metadata"), dict) else {}
                danmaku_data = {
                    "bvid": metadata.get("bvid") or comments.get("metadata", {}).get("bvid"),
                    "cid": metadata.get("cid") or comments.get("video_raw", {}).get("cid"),
                    "items": danmaku.get("items") or [],
                }
                save_danmaku_to_sqlite(danmaku_data, temp_path, replace=True)

        manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
        conn = connect(temp_path)
        try:
            ensure_schema(conn)
            if manifest:
                write_archive_meta(conn, manifest)
            checkpoint_for_handoff(conn)
        finally:
            conn.close()
        replace_file(temp_path, target_path)
        # A previous database at the target may have left a WAL behind; it must not be replayed
        # against the freshly imported file.
        remove_wal_sidecars(target_path)
    except Exception:
        remove_sqlite_file_with_sidecars(temp_path)
        raise
    return {
        "path": str(target_path),
        "bvids": [str(item.get("bvid") or item.get("comments", {}).get("metadata", {}).get("bvid") or "") for item in videos],
        "manifest": manifest,
        "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
    }


def select_export_bvids(source, *, bvids=None, owner_mid=None):
    selected_bvids = [str(value).strip() for value in (bvids or []) if str(value).strip()]
    owner_mid = str(owner_mid or "").strip()
    if bool(selected_bvids) == bool(owner_mid):
        raise ValueError("必须指定 owner_mid 或 bvids 之一")
    if owner_mid:
        video_rows = source.execute(
            "SELECT bvid FROM videos WHERE owner_mid = ? ORDER BY fetched_at DESC, bvid",
            (owner_mid,),
        ).fetchall()
        selected_bvids = [row["bvid"] for row in video_rows]
    else:
        source.execute("DROP TABLE IF EXISTS requested_export_bvids")
        source.execute("CREATE TEMP TABLE requested_export_bvids (bvid TEXT PRIMARY KEY)")
        source.executemany("INSERT OR IGNORE INTO requested_export_bvids (bvid) VALUES (?)", [(bvid,) for bvid in selected_bvids])
        video_rows = source.execute(
            """
            SELECT videos.bvid
            FROM videos
            JOIN requested_export_bvids ON requested_export_bvids.bvid = videos.bvid
            ORDER BY videos.fetched_at DESC, videos.bvid
            """
        ).fetchall()
        found_bvids = {row["bvid"] for row in video_rows}
        missing = [bvid for bvid in selected_bvids if bvid not in found_bvids]
        if missing:
            raise LookupError(f"数据库中没有视频：{', '.join(missing)}")
        selected_bvids = [row["bvid"] for row in video_rows]
    if not selected_bvids:
        raise LookupError("没有可导出的本地视频档案")
    return selected_bvids


def export_counts(source):
    return {
        "videos": source.execute("SELECT COUNT(*) FROM videos WHERE bvid IN (SELECT bvid FROM export_bvids)").fetchone()[0],
        "users": source.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE mid IN (
                SELECT DISTINCT mid
                FROM comments
                WHERE bvid IN (SELECT bvid FROM export_bvids)
                  AND mid IS NOT NULL
                  AND mid <> ''
            )
            """
        ).fetchone()[0],
        "comments": source.execute("SELECT COUNT(*) FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids)").fetchone()[0],
        "comment_pictures": source.execute(
            "SELECT COUNT(*) FROM comment_pictures WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))"
        ).fetchone()[0],
        "comment_emotes": source.execute(
            "SELECT COUNT(*) FROM comment_emotes WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN (SELECT bvid FROM export_bvids))"
        ).fetchone()[0],
        "danmaku": source.execute("SELECT COUNT(*) FROM danmaku WHERE bvid IN (SELECT bvid FROM export_bvids)").fetchone()[0],
    }
