import json
from pathlib import Path

from .archive_manifest import build_archive_manifest, read_archive_meta, write_archive_meta
from .archive_sqlite import copy_table_query, remove_sqlite_file_with_sidecars
from .storage import (
    connect,
    ensure_schema,
    load_comment_data,
    load_danmaku_data,
    save_comments_to_sqlite,
    save_danmaku_to_sqlite,
)


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

    source_path = Path(db_path).resolve()
    target_path = Path(target_path).resolve()
    if target_path == source_path:
        raise ValueError("导出目标不能覆盖当前主数据库")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    remove_sqlite_file_with_sidecars(target_path)

    source = connect(source_path)
    target = connect(target_path)
    try:
        ensure_schema(source)
        source.commit()
        ensure_schema(target)

        selected_bvids = select_export_bvids(source, bvids=selected_bvids or None, owner_mid=owner_mid or None)
        source.execute("DROP TABLE IF EXISTS export_bvids")
        source.execute("CREATE TEMP TABLE export_bvids (bvid TEXT PRIMARY KEY)")
        source.executemany("INSERT OR IGNORE INTO export_bvids (bvid) VALUES (?)", [(bvid,) for bvid in selected_bvids])

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
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target.execute("PRAGMA journal_mode = DELETE")
        target.commit()
        return {
            "path": str(target_path),
            "json_path": "",
            "bvids": selected_bvids,
            "counts": counts,
            "manifest": manifest,
            "size_bytes": target_path.stat().st_size if target_path.exists() else 0,
        }
    finally:
        source.close()
        target.close()


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
    source_path = Path(db_path).resolve()
    target_path = Path(target_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source = connect(source_path)
    try:
        ensure_schema(source)
        source.commit()
        selected_bvids = select_export_bvids(source, bvids=bvids, owner_mid=owner_mid)
        source.execute("DROP TABLE IF EXISTS export_bvids")
        source.execute("CREATE TEMP TABLE export_bvids (bvid TEXT PRIMARY KEY)")
        source.executemany("INSERT OR IGNORE INTO export_bvids (bvid) VALUES (?)", [(bvid,) for bvid in selected_bvids])
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

    videos = []
    for bvid in selected_bvids:
        comments = load_comment_data(source_path, bvid=bvid)
        danmaku = load_danmaku_data(source_path, bvid=bvid, limit=None)
        videos.append(
            {
                "bvid": bvid,
                "metadata": comments.get("metadata") or {},
                "video_raw": comments.get("video_raw") or {},
                "comments": comments.get("comments") or [],
                "comment_items": comments.get("comment_items") or [],
                "danmaku": danmaku,
            }
        )

    payload = {
        "format": "bilibili-comment-danmaku-json-data",
        "schema_version": 2,
        "manifest": manifest,
        "videos": videos,
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
        payload = json.loads(source_path.read_text(encoding="utf-8"))
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

    remove_sqlite_file_with_sidecars(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
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
        save_comments_to_sqlite(comments, target_path, replace=True)
        danmaku = item.get("danmaku")
        if isinstance(danmaku, dict):
            danmaku_data = {
                "bvid": danmaku.get("metadata", {}).get("bvid") or comments.get("metadata", {}).get("bvid"),
                "cid": danmaku.get("metadata", {}).get("cid") or comments.get("video_raw", {}).get("cid"),
                "items": danmaku.get("items") or [],
            }
            save_danmaku_to_sqlite(danmaku_data, target_path, replace=True)

    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    if manifest:
        conn = connect(target_path)
        try:
            ensure_schema(conn)
            write_archive_meta(conn, manifest)
            conn.commit()
        finally:
            conn.close()
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
