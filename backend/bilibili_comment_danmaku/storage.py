from collections import defaultdict
import binascii
from pathlib import Path
import shutil
import json
import sqlite3


DEFAULT_DATABASE_NAME = "comment_danmaku.db"
LEGACY_DATABASE_NAME = "comments.db"


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    bvid TEXT PRIMARY KEY,
    aid INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sort TEXT,
    api_comment_count INTEGER,
    top_level_comment_count INTEGER,
    expected_nested_comment_count INTEGER,
    nested_comment_count INTEGER,
    comment_total_count INTEGER,
    pic TEXT,
    video_cid TEXT,
    owner_mid TEXT,
    owner_name TEXT,
    owner_face TEXT,
    stat_view INTEGER,
    stat_danmaku INTEGER,
    stat_reply INTEGER,
    stat_favorite INTEGER,
    stat_coin INTEGER,
    stat_share INTEGER,
    stat_like INTEGER,
    pubdate INTEGER,
    desc TEXT,
    duration INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    mid TEXT PRIMARY KEY,
    uname TEXT,
    sex TEXT,
    sign TEXT,
    avatar TEXT,
    level INTEGER
);

CREATE TABLE IF NOT EXISTS comments (
    rpid TEXT PRIMARY KEY,
    bvid TEXT NOT NULL REFERENCES videos(bvid) ON DELETE CASCADE,
    level INTEGER NOT NULL,
    oid TEXT,
    type INTEGER,
    mid TEXT,
    root TEXT,
    parent TEXT,
    dialog TEXT,
    ctime INTEGER,
    time_iso TEXT,
    time_iso_utc TEXT,
    like_count INTEGER,
    rcount INTEGER,
    reply_count INTEGER,
    state INTEGER,
    attr INTEGER,
    message TEXT,
    ip_location TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    missing_since TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (mid) REFERENCES users(mid)
);

CREATE TABLE IF NOT EXISTS comment_pictures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rpid TEXT NOT NULL REFERENCES comments(rpid) ON DELETE CASCADE,
    img_src TEXT NOT NULL,
    img_width INTEGER,
    img_height INTEGER,
    img_size REAL,
    top_right_icon TEXT,
    play_gif_thumbnail INTEGER
);

CREATE TABLE IF NOT EXISTS comment_emotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rpid TEXT NOT NULL REFERENCES comments(rpid) ON DELETE CASCADE,
    text TEXT NOT NULL,
    url TEXT NOT NULL,
    jump_title TEXT,
    size INTEGER,
    package_id INTEGER,
    emote_type INTEGER
);

CREATE TABLE IF NOT EXISTS danmaku (
    dmid TEXT PRIMARY KEY,
    bvid TEXT NOT NULL REFERENCES videos(bvid) ON DELETE CASCADE,
    cid TEXT,
    progress REAL,
    mode INTEGER,
    font_size INTEGER,
    color INTEGER,
    ctime INTEGER,
    pool INTEGER,
    user_hash TEXT,
    weight INTEGER,
    like_count INTEGER NOT NULL DEFAULT 0,
    is_up_owner INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_bvid_ctime ON comments (bvid, ctime, rpid);
CREATE INDEX IF NOT EXISTS idx_comments_root ON comments (bvid, root, ctime, rpid);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments (bvid, parent);
CREATE INDEX IF NOT EXISTS idx_comments_mid ON comments (bvid, mid);
CREATE INDEX IF NOT EXISTS idx_comments_like ON comments (bvid, like_count DESC);
CREATE INDEX IF NOT EXISTS idx_pictures_rpid ON comment_pictures (rpid);
CREATE INDEX IF NOT EXISTS idx_emotes_rpid ON comment_emotes (rpid);
CREATE INDEX IF NOT EXISTS idx_danmaku_bvid_progress ON danmaku (bvid, progress, dmid);
CREATE INDEX IF NOT EXISTS idx_danmaku_bvid_ctime ON danmaku (bvid, ctime, dmid);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def prepare_database_path(db_path):
    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = db_path.with_name(LEGACY_DATABASE_NAME)
    if db_path.name == DEFAULT_DATABASE_NAME and not db_path.exists() and legacy_path.exists():
        shutil.copy2(legacy_path, db_path)
        for suffix in ("-wal", "-shm"):
            legacy_sidecar = legacy_path.with_name(f"{legacy_path.name}{suffix}")
            target_sidecar = db_path.with_name(f"{db_path.name}{suffix}")
            if legacy_sidecar.exists() and not target_sidecar.exists():
                shutil.copy2(legacy_sidecar, target_sidecar)
    return db_path


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

        if owner_mid:
            video_rows = source.execute(
                "SELECT bvid FROM videos WHERE owner_mid = ? ORDER BY fetched_at DESC, bvid",
                (owner_mid,),
            ).fetchall()
            selected_bvids = [row["bvid"] for row in video_rows]
        else:
            source.execute("DROP TABLE IF EXISTS requested_export_bvids")
            source.execute("CREATE TEMP TABLE requested_export_bvids (bvid TEXT PRIMARY KEY)")
            source.executemany(
                "INSERT OR IGNORE INTO requested_export_bvids (bvid) VALUES (?)",
                [(bvid,) for bvid in selected_bvids],
            )
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
        source.executemany(
            "INSERT OR IGNORE INTO requested_export_bvids (bvid) VALUES (?)",
            [(bvid,) for bvid in selected_bvids],
        )
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


def remove_sqlite_file_with_sidecars(path):
    path = Path(path)
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        if candidate.exists():
            candidate.unlink()


def copy_table_query(source, target, table, where_sql, values=()):
    source_columns = {row["name"] for row in source.execute(f"PRAGMA table_info({table})").fetchall()}
    target_columns = [row["name"] for row in target.execute(f"PRAGMA table_info({table})").fetchall()]
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        return 0

    column_sql = ", ".join(columns)
    insert_placeholders = ", ".join("?" for _ in columns)
    cursor = source.execute(f"SELECT {column_sql} FROM {table} WHERE {where_sql}", values)
    count = 0
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        target.executemany(
            f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({insert_placeholders})",
            [tuple(row[column] for column in columns) for row in rows],
        )
        count += len(rows)
    return count


def build_archive_manifest(
    source,
    selected_bvids,
    counts,
    *,
    archive_kind=None,
    label="",
    owner_mid="",
    owner_name="",
    source_path=None,
    target_path=None,
):
    video_rows = source.execute(
        """
        SELECT bvid, title, owner_mid, owner_name, fetched_at,
               COALESCE(comment_total_count, 0) AS declared_comment_count,
               (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid) AS comment_count,
               (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS danmaku_count
        FROM videos
        WHERE bvid IN (SELECT bvid FROM export_bvids)
        ORDER BY fetched_at DESC, bvid
        """
    ).fetchall()
    inferred_kind = archive_kind or infer_archive_kind(video_rows, owner_mid)
    return {
        "format": "bilibili-comment-danmaku-archive",
        "schema_version": 1,
        "archive_kind": inferred_kind,
        "label": label or default_archive_label(video_rows, inferred_kind),
        "owner_mid": owner_mid or single_value(row["owner_mid"] for row in video_rows),
        "owner_name": owner_name or single_value(row["owner_name"] for row in video_rows),
        "exported_at": utc_now_text(),
        "source_db": str(source_path) if source_path else "",
        "database_file": Path(target_path).name if target_path else "",
        "bvids": list(selected_bvids),
        "counts": counts,
        "videos": [
            {
                "bvid": row["bvid"],
                "title": row["title"],
                "owner_mid": row["owner_mid"] or "",
                "owner_name": row["owner_name"] or "",
                "fetched_at": row["fetched_at"] or "",
                "comment_count": row["comment_count"] or 0,
                "danmaku_count": row["danmaku_count"] or 0,
            }
            for row in video_rows
        ],
    }


def infer_archive_kind(video_rows, owner_mid=""):
    rows = list(video_rows)
    if len(rows) == 1:
        return "video"
    owner_values = {str(row["owner_mid"] or "") for row in rows if row["owner_mid"]}
    if owner_mid or (len(rows) > 1 and len(owner_values) == 1):
        return "up"
    return "collection"


def default_archive_label(video_rows, archive_kind):
    rows = list(video_rows)
    if not rows:
        return "archive"
    if archive_kind == "video":
        return rows[0]["title"] or rows[0]["bvid"]
    if archive_kind == "up":
        return rows[0]["owner_name"] or rows[0]["owner_mid"] or "UP archive"
    return f"{len(rows)} videos"


def single_value(values):
    seen = {str(value or "") for value in values if value}
    return next(iter(seen)) if len(seen) == 1 else ""


def write_archive_meta(conn, manifest):
    conn.executemany(
        "INSERT OR REPLACE INTO archive_meta (key, value) VALUES (?, ?)",
        [
            ("manifest", json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
            ("archive_kind", str(manifest.get("archive_kind") or "")),
            ("label", str(manifest.get("label") or "")),
            ("owner_mid", str(manifest.get("owner_mid") or "")),
            ("owner_name", str(manifest.get("owner_name") or "")),
            ("exported_at", str(manifest.get("exported_at") or "")),
        ],
    )


def read_archive_meta(conn):
    try:
        rows = conn.execute("SELECT key, value FROM archive_meta").fetchall()
    except sqlite3.OperationalError:
        return {}
    meta = {row["key"]: row["value"] for row in rows}
    manifest_text = meta.get("manifest")
    if manifest_text:
        try:
            manifest = json.loads(manifest_text)
            if isinstance(manifest, dict):
                meta["manifest"] = manifest
        except json.JSONDecodeError:
            pass
    return meta


def write_archive_manifest_file(target_path, manifest):
    manifest_path = Path(target_path).with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def utc_now_text():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_schema(conn):
    conn.executescript(SCHEMA_SQL)
    rename_video_column(conn, "api_all_count", "api_comment_count", "INTEGER")
    rename_video_column(conn, "top_level_count", "top_level_comment_count", "INTEGER")
    rename_video_column(conn, "expected_nested_reply_count", "expected_nested_comment_count", "INTEGER")
    rename_video_column(conn, "nested_reply_count", "nested_comment_count", "INTEGER")
    rename_video_column(conn, "flat_total_count", "comment_total_count", "INTEGER")
    ensure_video_column(conn, "video_cid", "TEXT")
    ensure_video_column(conn, "owner_mid", "TEXT")
    ensure_comment_column(conn, "first_seen_at", "TEXT")
    ensure_comment_column(conn, "last_seen_at", "TEXT")
    ensure_comment_column(conn, "missing_since", "TEXT")
    ensure_comment_column(conn, "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    ensure_danmaku_column(conn, "like_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_danmaku_column(conn, "is_up_owner", "INTEGER NOT NULL DEFAULT 0")
    backfill_comment_lifecycle(conn)


def ensure_comment_column(conn, name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(comments)").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE comments ADD COLUMN {name} {definition}")


def ensure_video_column(conn, name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE videos ADD COLUMN {name} {definition}")


def rename_video_column(conn, old_name, new_name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    if new_name not in columns:
        try:
            conn.execute(f"ALTER TABLE videos ADD COLUMN {new_name} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    if old_name in columns:
        conn.execute(f"UPDATE videos SET {new_name} = COALESCE({new_name}, {old_name})")


def ensure_danmaku_column(conn, name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(danmaku)").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE danmaku ADD COLUMN {name} {definition}")


def backfill_comment_lifecycle(conn):
    conn.execute(
        """
        UPDATE comments
        SET first_seen_at = COALESCE(
                first_seen_at,
                (SELECT fetched_at FROM videos WHERE videos.bvid = comments.bvid)
            ),
            last_seen_at = COALESCE(
                last_seen_at,
                (SELECT fetched_at FROM videos WHERE videos.bvid = comments.bvid)
            ),
            is_deleted = COALESCE(is_deleted, 0)
        WHERE first_seen_at IS NULL
           OR last_seen_at IS NULL
           OR is_deleted IS NULL
        """
    )


def iter_nodes(output_data):
    for top in output_data.get("comments", []):
        yield top
        for reply in top.get("replies", []) or []:
            yield reply


def extract_video_cid(video_raw):
    if not video_raw:
        return None
    if video_raw.get("cid"):
        return str(video_raw.get("cid"))
    pages = video_raw.get("pages") or []
    if pages and pages[0].get("cid"):
        return str(pages[0].get("cid"))
    return None


def save_comments_to_sqlite(output_data, db_path, replace=True):
    metadata = output_data["metadata"]
    video_raw = output_data["video_raw"]
    owner = video_raw.get("owner") or {}
    stat = video_raw.get("stat") or {}
    video_cid = extract_video_cid(video_raw)
    fetched_at = metadata["fetched_at"]
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        if replace:
            conn.execute(
                """
                UPDATE comments
                SET is_deleted = 1,
                    missing_since = COALESCE(missing_since, ?)
                WHERE bvid = ?
                """,
                (fetched_at, metadata["bvid"]),
            )

        conn.execute(
            """
            INSERT INTO videos (
                bvid, aid, title, source_url, fetched_at, sort, api_comment_count,
                top_level_comment_count, expected_nested_comment_count, nested_comment_count,
                comment_total_count, pic, video_cid, owner_mid, owner_name, owner_face, stat_view,
                stat_danmaku, stat_reply, stat_favorite, stat_coin, stat_share,
                stat_like, pubdate, desc, duration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                aid = excluded.aid,
                title = excluded.title,
                source_url = excluded.source_url,
                fetched_at = excluded.fetched_at,
                sort = excluded.sort,
                api_comment_count = excluded.api_comment_count,
                top_level_comment_count = excluded.top_level_comment_count,
                expected_nested_comment_count = excluded.expected_nested_comment_count,
                nested_comment_count = excluded.nested_comment_count,
                comment_total_count = excluded.comment_total_count,
                pic = excluded.pic,
                video_cid = excluded.video_cid,
                owner_mid = excluded.owner_mid,
                owner_name = excluded.owner_name,
                owner_face = excluded.owner_face,
                stat_view = excluded.stat_view,
                stat_danmaku = excluded.stat_danmaku,
                stat_reply = excluded.stat_reply,
                stat_favorite = excluded.stat_favorite,
                stat_coin = excluded.stat_coin,
                stat_share = excluded.stat_share,
                stat_like = excluded.stat_like,
                pubdate = excluded.pubdate,
                desc = excluded.desc,
                duration = excluded.duration
            """,
            (
                metadata["bvid"],
                metadata["aid"],
                metadata["title"],
                metadata["source_url"],
                metadata["fetched_at"],
                metadata.get("sort"),
                metadata.get("api_comment_count"),
                metadata.get("top_level_comment_count"),
                metadata.get("expected_nested_comment_count"),
                metadata.get("nested_comment_count"),
                metadata.get("comment_total_count"),
                video_raw.get("pic"),
                video_cid,
                owner.get("mid"),
                owner.get("name"),
                owner.get("face"),
                stat.get("view"),
                stat.get("danmaku"),
                stat.get("reply"),
                stat.get("favorite"),
                stat.get("coin"),
                stat.get("share"),
                stat.get("like"),
                video_raw.get("pubdate"),
                video_raw.get("desc"),
                video_raw.get("duration"),
            ),
        )

        comment_rows = []
        user_rows = {}
        picture_rows = []
        emote_rows = []
        scraped_rpids = []
        for node in iter_nodes(output_data):
            normalized = node["normalized"]
            user = normalized.get("user") or {}
            if user.get("mid"):
                user_rows[str(user.get("mid"))] = (
                    str(user.get("mid")),
                    user.get("uname"),
                    user.get("sex"),
                    user.get("sign"),
                    user.get("avatar"),
                    user.get("level"),
                )

            rpid = str(normalized.get("rpid"))
            scraped_rpids.append(rpid)
            comment_rows.append(
                (
                    rpid,
                    metadata["bvid"],
                    normalized.get("level"),
                    normalized.get("oid"),
                    normalized.get("type"),
                    normalized.get("mid"),
                    normalized.get("root"),
                    normalized.get("parent"),
                    normalized.get("dialog"),
                    normalized.get("ctime"),
                    normalized.get("time_iso"),
                    normalized.get("time_iso_utc"),
                    normalized.get("like"),
                    normalized.get("rcount"),
                    normalized.get("count"),
                    normalized.get("state"),
                    normalized.get("attr"),
                    normalized.get("message"),
                    normalized.get("ip_location"),
                )
            )

            for picture in normalized.get("pictures") or []:
                if not picture.get("img_src"):
                    continue
                picture_rows.append(
                    (
                        rpid,
                        picture.get("img_src"),
                        picture.get("img_width"),
                        picture.get("img_height"),
                        picture.get("img_size"),
                        picture.get("top_right_icon"),
                        1 if picture.get("play_gif_thumbnail") else 0,
                    )
                )

            for text, emote in (normalized.get("emote") or {}).items():
                if not text or not emote.get("url"):
                    continue
                meta = emote.get("meta") or {}
                emote_rows.append(
                    (
                        rpid,
                        text,
                        emote.get("url"),
                        emote.get("jump_title"),
                        meta.get("size"),
                        emote.get("package_id"),
                        emote.get("type"),
                    )
                )

        conn.executemany(
            """
            INSERT OR REPLACE INTO users (
                mid, uname, sex, sign, avatar, level
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            list(user_rows.values()),
        )
        if scraped_rpids:
            placeholders = ",".join("?" for _ in scraped_rpids)
            conn.execute(f"DELETE FROM comment_pictures WHERE rpid IN ({placeholders})", scraped_rpids)
            conn.execute(f"DELETE FROM comment_emotes WHERE rpid IN ({placeholders})", scraped_rpids)
        conn.executemany(
            """
            INSERT INTO comments (
                rpid, bvid, level, oid, type, mid, root, parent, dialog, ctime,
                time_iso, time_iso_utc, like_count, rcount, reply_count, state,
                attr, message, ip_location, first_seen_at, last_seen_at, missing_since, is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
            ON CONFLICT(rpid) DO UPDATE SET
                bvid = excluded.bvid,
                level = excluded.level,
                oid = excluded.oid,
                type = excluded.type,
                mid = excluded.mid,
                root = excluded.root,
                parent = excluded.parent,
                dialog = excluded.dialog,
                ctime = excluded.ctime,
                time_iso = excluded.time_iso,
                time_iso_utc = excluded.time_iso_utc,
                like_count = excluded.like_count,
                rcount = excluded.rcount,
                reply_count = excluded.reply_count,
                state = excluded.state,
                attr = excluded.attr,
                message = excluded.message,
                ip_location = excluded.ip_location,
                first_seen_at = COALESCE(comments.first_seen_at, excluded.first_seen_at),
                last_seen_at = excluded.last_seen_at,
                missing_since = NULL,
                is_deleted = 0
            """,
            [row + (fetched_at, fetched_at) for row in comment_rows],
        )
        conn.executemany(
            """
            INSERT INTO comment_pictures (
                rpid, img_src, img_width, img_height, img_size, top_right_icon, play_gif_thumbnail
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            picture_rows,
        )
        conn.executemany(
            """
            INSERT INTO comment_emotes (
                rpid, text, url, jump_title, size, package_id, emote_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            emote_rows,
        )
        conn.commit()
        return {
            "db": str(Path(db_path).resolve()),
            "bvid": metadata["bvid"],
            "top_level_comment_count": conn.execute(
                "SELECT COUNT(*) FROM comments WHERE bvid = ? AND level = 1", (metadata["bvid"],)
            ).fetchone()[0],
            "nested_comment_count": conn.execute(
                "SELECT COUNT(*) FROM comments WHERE bvid = ? AND level = 2", (metadata["bvid"],)
            ).fetchone()[0],
            "total_count": conn.execute(
                "SELECT COUNT(*) FROM comments WHERE bvid = ?", (metadata["bvid"],)
            ).fetchone()[0],
            "deleted_count": conn.execute(
                "SELECT COUNT(*) FROM comments WHERE bvid = ? AND is_deleted = 1", (metadata["bvid"],)
            ).fetchone()[0],
        }
    finally:
        conn.close()


def save_danmaku_to_sqlite(danmaku_data, db_path, replace=True):
    bvid = danmaku_data["bvid"]
    items = danmaku_data.get("items") or []
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        video = conn.execute("SELECT owner_mid FROM videos WHERE bvid = ?", (bvid,)).fetchone()
        owner_hash = danmaku_user_hash(video["owner_mid"]) if video and video["owner_mid"] else None
        if replace:
            conn.execute("DELETE FROM danmaku WHERE bvid = ?", (bvid,))
        conn.executemany(
            """
            INSERT OR REPLACE INTO danmaku (
                dmid, bvid, cid, progress, mode, font_size, color, ctime,
                pool, user_hash, weight, like_count, is_up_owner, content, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["dmid"],
                    item["bvid"],
                    item.get("cid"),
                    item.get("progress"),
                    item.get("mode"),
                    item.get("font_size"),
                    item.get("color"),
                    item.get("ctime"),
                    item.get("pool"),
                    item.get("user_hash"),
                    item.get("weight"),
                    value_or_zero(item.get("like_count")),
                    1 if owner_hash and item.get("user_hash") == owner_hash else 0,
                    item.get("content") or "",
                    item.get("fetched_at"),
                )
                for item in items
            ],
        )
        conn.commit()
        return {
            "bvid": bvid,
            "danmaku_count": conn.execute(
                "SELECT COUNT(*) FROM danmaku WHERE bvid = ?", (bvid,)
            ).fetchone()[0],
        }
    finally:
        conn.close()


def load_danmaku_data(db_path, bvid=None, limit=None):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        if bvid:
            video = conn.execute("SELECT * FROM videos WHERE bvid = ?", (bvid,)).fetchone()
        else:
            video = conn.execute("SELECT * FROM videos ORDER BY fetched_at DESC LIMIT 1").fetchone()
        if not video:
            raise LookupError("video not found")

        stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                MIN(progress) AS min_progress,
                MAX(progress) AS max_progress,
                MAX(fetched_at) AS fetched_at
            FROM danmaku
            WHERE bvid = ?
            """,
            (video["bvid"],),
        ).fetchone()
        if limit is None:
            rows = conn.execute(
                """
                SELECT *
                FROM danmaku
                WHERE bvid = ?
                ORDER BY progress ASC, dmid ASC
                """,
                (video["bvid"],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM danmaku
                WHERE bvid = ?
                ORDER BY progress ASC, dmid ASC
                LIMIT ?
                """,
                (video["bvid"], limit),
            ).fetchall()
        buckets = conn.execute(
            """
            SELECT CAST(progress / 10 AS INTEGER) * 10 AS bucket_start, COUNT(*) AS count
            FROM danmaku
            WHERE bvid = ?
            GROUP BY bucket_start
            ORDER BY bucket_start ASC
            """,
            (video["bvid"],),
        ).fetchall()
        return {
            "metadata": {
                "bvid": video["bvid"],
                "cid": video["video_cid"],
                "title": video["title"],
                "duration": video["duration"],
                "total_count": value_or_zero(stats["total_count"]),
                "fetched_at": stats["fetched_at"],
                "min_progress": stats["min_progress"],
                "max_progress": stats["max_progress"],
                "limit": limit if limit is not None else value_or_zero(stats["total_count"]),
            },
            "items": [danmaku_from_row(row) for row in rows],
            "buckets": [
                {
                    "bucket_start": value_or_zero(row["bucket_start"]),
                    "label": format_progress(value_or_zero(row["bucket_start"])),
                    "count": value_or_zero(row["count"]),
                }
                for row in buckets
            ],
        }
    finally:
        conn.close()


def danmaku_from_row(row):
    return {
        "dmid": row["dmid"],
        "bvid": row["bvid"],
        "cid": row["cid"],
        "progress": row["progress"],
        "mode": row["mode"],
        "font_size": row["font_size"],
        "color": row["color"],
        "ctime": row["ctime"],
        "pool": row["pool"],
        "user_hash": row["user_hash"],
        "weight": row["weight"],
        "like_count": value_or_zero(row["like_count"]),
        "is_up_owner": bool(row["is_up_owner"]),
        "content": row["content"],
        "fetched_at": row["fetched_at"],
    }


def format_progress(seconds):
    minutes = int(seconds) // 60
    rest = int(seconds) % 60
    return f"{minutes:02d}:{rest:02d}"


def danmaku_user_hash(mid):
    if mid is None:
        return None
    return format(binascii.crc32(str(mid).encode("utf-8")) & 0xFFFFFFFF, "08x")


def restore_missing_from_legacy_sqlite(db_path, legacy_db_path, bvid=None, missing_since=None):
    conn = connect(db_path)
    legacy = connect(legacy_db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        if bvid is None:
            video = conn.execute("SELECT bvid, fetched_at FROM videos ORDER BY fetched_at DESC LIMIT 1").fetchone()
            if not video:
                raise LookupError("video not found")
            bvid = video["bvid"]
            current_fetched_at = video["fetched_at"]
        else:
            video = conn.execute("SELECT bvid, fetched_at FROM videos WHERE bvid = ?", (bvid,)).fetchone()
            current_fetched_at = video["fetched_at"] if video else None

        legacy_video = legacy.execute("SELECT fetched_at FROM videos WHERE bvid = ?", (bvid,)).fetchone()
        legacy_fetched_at = legacy_video["fetched_at"] if legacy_video else current_fetched_at
        missing_since = missing_since or current_fetched_at or legacy_fetched_at

        existing = {
            str(row["rpid"])
            for row in conn.execute("SELECT rpid FROM comments WHERE bvid = ?", (bvid,)).fetchall()
        }
        legacy_rows = legacy.execute(
            "SELECT * FROM comments WHERE bvid = ? ORDER BY ctime ASC, rpid ASC",
            (bvid,),
        ).fetchall()
        missing_rows = [row for row in legacy_rows if str(row["rpid"]) not in existing]
        if not missing_rows:
            return {"bvid": bvid, "restored_count": 0, "missing_since": missing_since}

        user_rows = {}
        comment_rows = []
        picture_rows = []
        emote_rows = []
        for row in missing_rows:
            normalized = json.loads(row["normalized_json"])
            user = normalized.get("user") or json.loads(row["user_json"])
            if user.get("mid"):
                user_rows[str(user.get("mid"))] = (
                    str(user.get("mid")),
                    user.get("uname"),
                    user.get("sex"),
                    user.get("sign"),
                    user.get("avatar"),
                    user.get("level"),
                )

            rpid = str(normalized.get("rpid") or row["rpid"])
            comment_rows.append(
                (
                    rpid,
                    bvid,
                    normalized.get("level"),
                    normalized.get("oid"),
                    normalized.get("type"),
                    normalized.get("mid"),
                    normalized.get("root"),
                    normalized.get("parent"),
                    normalized.get("dialog"),
                    normalized.get("ctime"),
                    normalized.get("time_iso"),
                    normalized.get("time_iso_utc"),
                    normalized.get("like"),
                    normalized.get("rcount"),
                    normalized.get("count"),
                    normalized.get("state"),
                    normalized.get("attr"),
                    normalized.get("message"),
                    normalized.get("ip_location"),
                    legacy_fetched_at,
                    legacy_fetched_at,
                    missing_since,
                )
            )

            for picture in normalized.get("pictures") or []:
                if not picture.get("img_src"):
                    continue
                picture_rows.append(
                    (
                        rpid,
                        picture.get("img_src"),
                        picture.get("img_width"),
                        picture.get("img_height"),
                        picture.get("img_size"),
                        picture.get("top_right_icon"),
                        1 if picture.get("play_gif_thumbnail") else 0,
                    )
                )

            for text, emote in (normalized.get("emote") or {}).items():
                if not text or not emote.get("url"):
                    continue
                meta = emote.get("meta") or {}
                emote_rows.append(
                    (
                        rpid,
                        text,
                        emote.get("url"),
                        emote.get("jump_title"),
                        meta.get("size"),
                        emote.get("package_id"),
                        emote.get("type"),
                    )
                )

        conn.executemany(
            """
            INSERT OR REPLACE INTO users (
                mid, uname, sex, sign, avatar, level
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            list(user_rows.values()),
        )
        conn.executemany(
            """
            INSERT INTO comments (
                rpid, bvid, level, oid, type, mid, root, parent, dialog, ctime,
                time_iso, time_iso_utc, like_count, rcount, reply_count, state,
                attr, message, ip_location, first_seen_at, last_seen_at, missing_since, is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(rpid) DO NOTHING
            """,
            comment_rows,
        )
        conn.executemany(
            """
            INSERT INTO comment_pictures (
                rpid, img_src, img_width, img_height, img_size, top_right_icon, play_gif_thumbnail
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            picture_rows,
        )
        conn.executemany(
            """
            INSERT INTO comment_emotes (
                rpid, text, url, jump_title, size, package_id, emote_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            emote_rows,
        )
        conn.commit()
        return {
            "bvid": bvid,
            "restored_count": len(missing_rows),
            "missing_since": missing_since,
        }
    finally:
        legacy.close()
        conn.close()


def load_comment_data(db_path, bvid=None):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        if bvid:
            video = conn.execute("SELECT * FROM videos WHERE bvid = ?", (bvid,)).fetchone()
        else:
            video = conn.execute("SELECT * FROM videos ORDER BY fetched_at DESC LIMIT 1").fetchone()
        if not video:
            raise LookupError("video not found")

        rows = conn.execute(
            """
            SELECT
                c.*,
                u.uname AS user_uname,
                u.sex AS user_sex,
                u.sign AS user_sign,
                u.avatar AS user_avatar,
                u.level AS user_level
            FROM comments c
            LEFT JOIN users u ON u.mid = c.mid
            WHERE c.bvid = ?
            ORDER BY ctime ASC, rpid ASC
            """,
            (video["bvid"],),
        ).fetchall()

        pictures_by_rpid = load_pictures_by_rpid(conn, video["bvid"])
        emotes_by_rpid = load_emotes_by_rpid(conn, video["bvid"])
        nodes = []
        by_rpid = {}
        for row in rows:
            normalized = normalized_from_row(row)
            normalized["is_up_owner"] = bool(video["owner_mid"] and normalized["mid"] == str(video["owner_mid"]))
            rpid = str(normalized["rpid"])
            if pictures_by_rpid.get(rpid):
                normalized["pictures"] = pictures_by_rpid[rpid]
            if emotes_by_rpid.get(rpid):
                normalized["emote"] = emotes_by_rpid[rpid]
            node = {"normalized": normalized, "raw": {}}
            nodes.append(node)
            by_rpid[rpid] = node

        top_level = []
        for node in nodes:
            normalized = node["normalized"]
            if normalized.get("level") == 1:
                node["replies"] = []
                top_level.append(node)

        for node in nodes:
            normalized = node["normalized"]
            if normalized.get("level") != 2:
                continue
            root_node = by_rpid.get(str(normalized.get("root")))
            if root_node is not None:
                root_node.setdefault("replies", []).append(node)

        top_level.sort(key=node_sort_key)
        for node in top_level:
            node["replies"].sort(key=node_sort_key)

        return {
            "metadata": metadata_from_video(video, rows),
            "video_raw": video_raw_from_video(video),
            "comments": top_level,
            "comment_items": sorted(nodes, key=node_sort_key),
        }
    finally:
        conn.close()


def list_video_summaries(db_path):
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        rows = conn.execute(
            """
            SELECT
                v.*,
                COALESCE(c.comment_total_count_actual, 0) AS comment_total_count_actual,
                COALESCE(c.active_comment_count, 0) AS active_comment_count,
                COALESCE(c.deleted_comment_count, 0) AS deleted_comment_count,
                COALESCE(c.top_level_comment_count_actual, 0) AS top_level_comment_count_actual,
                COALESCE(c.nested_comment_count_actual, 0) AS nested_comment_count_actual,
                COALESCE(c.comment_like_count, 0) AS comment_like_count,
                c.latest_comment_ctime,
                COALESCE(d.danmaku_count, 0) AS danmaku_count,
                d.latest_danmaku_fetched_at
            FROM videos v
            LEFT JOIN (
                SELECT
                    bvid,
                    COUNT(rpid) AS comment_total_count_actual,
                    SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS active_comment_count,
                    SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END) AS deleted_comment_count,
                    SUM(CASE WHEN level = 1 THEN 1 ELSE 0 END) AS top_level_comment_count_actual,
                    SUM(CASE WHEN level = 2 THEN 1 ELSE 0 END) AS nested_comment_count_actual,
                    SUM(COALESCE(like_count, 0)) AS comment_like_count,
                    MAX(ctime) AS latest_comment_ctime
                FROM comments
                GROUP BY bvid
            ) c ON c.bvid = v.bvid
            LEFT JOIN (
                SELECT
                    bvid,
                    COUNT(dmid) AS danmaku_count,
                    MAX(fetched_at) AS latest_danmaku_fetched_at
                FROM danmaku
                GROUP BY bvid
            ) d ON d.bvid = v.bvid
            ORDER BY v.fetched_at DESC
            """
        ).fetchall()
        return [video_summary_from_row(row) for row in rows]
    finally:
        conn.close()


def video_summary_from_row(row):
    total = value_or_zero(row["comment_total_count_actual"])
    deleted = value_or_zero(row["deleted_comment_count"])
    active = value_or_zero(row["active_comment_count"])
    return {
        "bvid": row["bvid"],
        "aid": row["aid"],
        "title": row["title"],
        "source_url": row["source_url"],
        "fetched_at": row["fetched_at"],
        "pic": row["pic"],
        "video_cid": value_or_empty(row["video_cid"]),
        "owner_mid": value_or_empty(row["owner_mid"]),
        "owner_name": row["owner_name"],
        "owner_face": row["owner_face"],
        "stat_view": value_or_zero(row["stat_view"]),
        "stat_reply": value_or_zero(row["stat_reply"]),
        "stat_like": value_or_zero(row["stat_like"]),
        "comment_total_count": total,
        "active_comment_count": active,
        "deleted_comment_count": deleted,
        "top_level_comment_count": value_or_zero(row["top_level_comment_count_actual"]),
        "nested_comment_count": value_or_zero(row["nested_comment_count_actual"]),
        "comment_like_count": value_or_zero(row["comment_like_count"]),
        "latest_comment_ctime": row["latest_comment_ctime"],
        "danmaku_count": value_or_zero(row["danmaku_count"]),
        "latest_danmaku_fetched_at": row["latest_danmaku_fetched_at"],
    }


def load_pictures_by_rpid(conn, bvid):
    rows = conn.execute(
        """
        SELECT *
        FROM comment_pictures
        WHERE rpid IN (SELECT rpid FROM comments WHERE bvid = ?)
        ORDER BY id ASC
        """,
        (bvid,),
    ).fetchall()
    pictures = defaultdict(list)
    for row in rows:
        pictures[str(row["rpid"])].append(
            {
                "img_src": row["img_src"],
                "img_width": row["img_width"],
                "img_height": row["img_height"],
                "img_size": row["img_size"],
                "top_right_icon": row["top_right_icon"],
                "play_gif_thumbnail": bool(row["play_gif_thumbnail"]),
            }
        )
    return pictures


def load_emotes_by_rpid(conn, bvid):
    rows = conn.execute(
        """
        SELECT *
        FROM comment_emotes
        WHERE rpid IN (SELECT rpid FROM comments WHERE bvid = ?)
        ORDER BY id ASC
        """,
        (bvid,),
    ).fetchall()
    emotes = defaultdict(dict)
    for row in rows:
        text = row["text"]
        emotes[str(row["rpid"])][text] = {
            "text": text,
            "url": row["url"],
            "jump_title": row["jump_title"],
            "meta": {"size": row["size"]},
            "package_id": row["package_id"],
            "type": row["emote_type"],
        }
    return emotes


def value_or_zero(value):
    return 0 if value is None else value


def value_or_empty(value):
    return "" if value is None else str(value)


def normalized_from_row(row):
    mid = value_or_empty(row["mid"])
    return {
        "level": value_or_zero(row["level"]),
        "rpid": value_or_empty(row["rpid"]),
        "oid": value_or_empty(row["oid"]),
        "type": value_or_zero(row["type"]),
        "mid": mid,
        "root": value_or_empty(row["root"]),
        "parent": value_or_empty(row["parent"]),
        "dialog": value_or_empty(row["dialog"]),
        "ctime": value_or_zero(row["ctime"]),
        "time_iso": value_or_empty(row["time_iso"]),
        "time_iso_utc": value_or_empty(row["time_iso_utc"]),
        "like": value_or_zero(row["like_count"]),
        "rcount": value_or_zero(row["rcount"]),
        "count": value_or_zero(row["reply_count"]),
        "state": value_or_zero(row["state"]),
        "attr": value_or_zero(row["attr"]),
        "message": row["message"] or "",
        "ip_location": row["ip_location"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "missing_since": row["missing_since"],
        "is_deleted": bool(row["is_deleted"]),
        "user": {
            "mid": mid,
            "uname": row["user_uname"] or "",
            "sex": row["user_sex"],
            "sign": row["user_sign"],
            "avatar": row["user_avatar"],
            "level": row["user_level"],
        },
    }


def metadata_from_video(video, comment_rows):
    top_level_comment_count = sum(1 for row in comment_rows if row["level"] == 1)
    nested_comment_count = sum(1 for row in comment_rows if row["level"] == 2)
    comment_total_count = len(comment_rows)
    deleted_count = sum(1 for row in comment_rows if row["is_deleted"])
    return {
        "source_url": video["source_url"],
        "bvid": video["bvid"],
        "aid": video["aid"],
        "title": video["title"],
        "fetched_at": video["fetched_at"],
        "sort": video["sort"] or "ctime_ascending",
        "api_comment_count": count_or_default(video["api_comment_count"], top_level_comment_count),
        "top_level_comment_count": top_level_comment_count,
        "expected_nested_comment_count": count_or_default(video["expected_nested_comment_count"], nested_comment_count),
        "nested_comment_count": nested_comment_count,
        "comment_total_count": comment_total_count,
        "active_comment_count": comment_total_count - deleted_count,
        "deleted_comment_count": deleted_count,
        "child_fetch_summary": [],
        "notes": [
            "comments are loaded from normalized SQLite tables",
            "raw Bilibili JSON blobs are not stored in the database",
        ],
    }


def video_raw_from_video(video):
    return {
        "pic": video["pic"],
        "cid": video["video_cid"],
        "owner": {
            "mid": video["owner_mid"],
            "name": video["owner_name"],
            "face": video["owner_face"],
        },
        "stat": {
            "view": video["stat_view"],
            "danmaku": video["stat_danmaku"],
            "reply": video["stat_reply"],
            "favorite": video["stat_favorite"],
            "coin": video["stat_coin"],
            "share": video["stat_share"],
            "like": video["stat_like"],
        },
        "pubdate": video["pubdate"],
        "desc": video["desc"],
        "duration": video["duration"],
    }


def count_or_default(value, default):
    return default if value is None else value


def node_sort_key(node):
    normalized = node.get("normalized") or {}
    ctime = normalized.get("ctime") or 0
    rpid = str(normalized.get("rpid") or "")
    return ctime, rpid

