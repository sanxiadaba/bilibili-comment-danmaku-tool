from collections import defaultdict
import binascii
from pathlib import Path
import shutil
import sqlite3


DEFAULT_DATABASE_NAME = "comment_danmaku.db"
LEGACY_DATABASE_NAME = "comments.db"
DEFAULT_WAL_CHECKPOINT_THRESHOLD_BYTES = 32 * 1024 * 1024
DEFAULT_WAL_JOURNAL_SIZE_LIMIT_BYTES = 32 * 1024 * 1024
DELETE_COMMENT_BATCH_SIZE = 5000
DELETE_DANMAKU_BATCH_SIZE = 10000
DELETE_VIDEO_BATCH_SIZE = 200


SCHEMA_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_comments_bvid_deleted ON comments (bvid, is_deleted);
CREATE INDEX IF NOT EXISTS idx_comments_bvid_level ON comments (bvid, level);
CREATE INDEX IF NOT EXISTS idx_comments_root ON comments (bvid, root, ctime, rpid);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments (bvid, parent);
CREATE INDEX IF NOT EXISTS idx_comments_mid ON comments (bvid, mid);
CREATE INDEX IF NOT EXISTS idx_comments_like ON comments (bvid, like_count DESC);
CREATE INDEX IF NOT EXISTS idx_videos_fetched_at ON videos (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_owner_mid ON videos (owner_mid, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_mid_global ON comments (mid);
CREATE INDEX IF NOT EXISTS idx_pictures_rpid ON comment_pictures (rpid);
CREATE INDEX IF NOT EXISTS idx_emotes_rpid ON comment_emotes (rpid);
CREATE INDEX IF NOT EXISTS idx_danmaku_bvid ON danmaku (bvid);
CREATE INDEX IF NOT EXISTS idx_danmaku_bvid_progress ON danmaku (bvid, progress, dmid);
CREATE INDEX IF NOT EXISTS idx_danmaku_bvid_ctime ON danmaku (bvid, ctime, dmid);
"""


SQLITE_CACHE_SIZE_KB = 64 * 1024
SQLITE_MMAP_SIZE_BYTES = 256 * 1024 * 1024


def connect(db_path, readonly=False):
    if readonly:
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute(f"PRAGMA cache_size = {-SQLITE_CACHE_SIZE_KB}")
    conn.execute(f"PRAGMA mmap_size = {SQLITE_MMAP_SIZE_BYTES}")
    conn.execute("PRAGMA wal_autocheckpoint = 512")
    conn.execute(f"PRAGMA journal_size_limit = {DEFAULT_WAL_JOURNAL_SIZE_LIMIT_BYTES}")
    return conn


def connect_readonly(db_path):
    return connect(db_path, readonly=True)


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


def ensure_schema(conn, journal_mode="WAL"):
    if journal_mode:
        conn.execute(f"PRAGMA journal_mode = {journal_mode}")
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


def list_video_summaries_page(db_path, limit=40, offset=0, include_owners=True):
    limit = max(1, min(int(limit or 40), 200))
    offset = max(0, int(offset or 0))
    conn = connect_readonly(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        rows = conn.execute(
            """
            WITH page_videos AS (
                SELECT *
                FROM videos
                ORDER BY fetched_at DESC
                LIMIT ? OFFSET ?
            )
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
            FROM page_videos v
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
                WHERE bvid IN (SELECT bvid FROM page_videos)
                GROUP BY bvid
            ) c ON c.bvid = v.bvid
            LEFT JOIN (
                SELECT
                    bvid,
                    COUNT(dmid) AS danmaku_count,
                    MAX(fetched_at) AS latest_danmaku_fetched_at
                FROM danmaku
                WHERE bvid IN (SELECT bvid FROM page_videos)
                GROUP BY bvid
            ) d ON d.bvid = v.bvid
            ORDER BY v.fetched_at DESC
            """,
            (limit, offset),
        ).fetchall()
        videos = [video_summary_from_row(row) for row in rows]
        payload = {
            "videos": videos,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(videos) < total,
        }
        if include_owners:
            payload["owners"] = list_owner_summaries(conn)
        return payload
    finally:
        conn.close()


def list_owner_summaries(conn):
    page_count = conn.execute("PRAGMA page_count").fetchone()[0] or 0
    page_size = conn.execute("PRAGMA page_size").fetchone()[0] or 0
    freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0] or 0
    used_bytes = max(0, (page_count - freelist_count) * page_size)
    rows = conn.execute(
        """
        WITH owner_videos AS (
            SELECT
                CASE
                    WHEN owner_mid IS NOT NULL AND owner_mid <> '' THEN 'mid:' || owner_mid
                    ELSE 'unknown:' || COALESCE(NULLIF(owner_name, ''), 'Unknown')
                END AS owner_key,
                MAX(COALESCE(NULLIF(owner_mid, ''), '')) AS owner_mid,
                COALESCE(NULLIF(owner_name, ''), 'Unknown') AS owner_name,
                COUNT(*) AS video_count
            FROM videos
            GROUP BY owner_key, owner_name
        ),
        comment_stats AS (
            SELECT
                CASE
                    WHEN v.owner_mid IS NOT NULL AND v.owner_mid <> '' THEN 'mid:' || v.owner_mid
                    ELSE 'unknown:' || COALESCE(NULLIF(v.owner_name, ''), 'Unknown')
                END AS owner_key,
                SUM(c.comment_count) AS comment_count
            FROM videos v
            JOIN (
                SELECT bvid, COUNT(*) AS comment_count
                FROM comments
                GROUP BY bvid
            ) c ON c.bvid = v.bvid
            GROUP BY owner_key
        ),
        danmaku_stats AS (
            SELECT
                CASE
                    WHEN v.owner_mid IS NOT NULL AND v.owner_mid <> '' THEN 'mid:' || v.owner_mid
                    ELSE 'unknown:' || COALESCE(NULLIF(v.owner_name, ''), 'Unknown')
                END AS owner_key,
                SUM(d.danmaku_count) AS danmaku_count
            FROM videos v
            JOIN (
                SELECT bvid, COUNT(*) AS danmaku_count
                FROM danmaku
                GROUP BY bvid
            ) d ON d.bvid = v.bvid
            GROUP BY owner_key
        ),
        weighted AS (
            SELECT
                owner_videos.owner_key,
                owner_videos.owner_mid,
                owner_videos.owner_name,
                owner_videos.video_count,
                COALESCE(comment_stats.comment_count, 0) AS comment_count,
                COALESCE(danmaku_stats.danmaku_count, 0) AS danmaku_count,
                (
                    owner_videos.video_count * 4096
                    + COALESCE(comment_stats.comment_count, 0) * 900
                    + COALESCE(danmaku_stats.danmaku_count, 0) * 260
                ) AS storage_weight
            FROM owner_videos
            LEFT JOIN comment_stats ON comment_stats.owner_key = owner_videos.owner_key
            LEFT JOIN danmaku_stats ON danmaku_stats.owner_key = owner_videos.owner_key
        )
        SELECT
            weighted.*,
            SUM(storage_weight) OVER () AS total_storage_weight
        FROM weighted
        ORDER BY video_count DESC, comment_count DESC, owner_name ASC
        """,
    ).fetchall()
    return [
        {
            "key": row["owner_key"],
            "name": row["owner_name"],
            "owner_mid": value_or_empty(row["owner_mid"]),
            "video_count": value_or_zero(row["video_count"]),
            "comment_count": value_or_zero(row["comment_count"]),
            "danmaku_count": value_or_zero(row["danmaku_count"]),
            "storage_bytes": estimate_owner_storage_bytes(
                used_bytes,
                value_or_zero(row["storage_weight"]),
                value_or_zero(row["total_storage_weight"]),
            ),
        }
        for row in rows
    ]


def estimate_owner_storage_bytes(used_bytes, owner_weight, total_weight):
    if used_bytes <= 0 or owner_weight <= 0 or total_weight <= 0:
        return 0
    return int(round(used_bytes * owner_weight / total_weight))


def delete_videos_from_sqlite(db_path, bvids, vacuum=True, progress_callback=None):
    selected_bvids = [str(item).strip() for item in bvids if str(item).strip()]
    if not selected_bvids:
        raise ValueError("请选择要删除的视频")

    db_path = Path(db_path)
    size_before = db_path.stat().st_size if db_path.exists() else 0
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        existing_rows = conn.execute(
            f"""
            SELECT bvid, title, owner_mid, owner_name
            FROM videos
            WHERE bvid IN ({placeholders(len(selected_bvids))})
            ORDER BY fetched_at DESC
            """,
            selected_bvids,
        ).fetchall()
        if not existing_rows:
            raise LookupError("没有找到要删除的视频")

        existing_bvids = [row["bvid"] for row in existing_rows]
        existing_bvid_set = set(existing_bvids)
        counts_before = count_archive_rows(conn, existing_bvids)
        conn.commit()
        conn.close()
        conn = None
        cleanup = delete_video_rows_chunked(db_path, existing_bvids, progress_callback=progress_callback)
        if vacuum:
            conn = connect(db_path)
            conn.execute("VACUUM")
            conn.close()
            conn = None
        else:
            checkpoint_database(db_path, truncate=True)
        size_after = db_path.stat().st_size if db_path.exists() else 0
        return {
            "deleted_bvids": existing_bvids,
            "deleted_videos": len(existing_bvids),
            "missing_bvids": [bvid for bvid in selected_bvids if bvid not in existing_bvid_set],
            "videos": [video_delete_summary(row) for row in existing_rows],
            "counts": counts_before,
            "size_before": size_before,
            "size_after": size_after,
            "bytes_reclaimed": max(0, size_before - size_after),
            "vacuum_deferred": not vacuum,
            "wal_before": cleanup["wal_before"],
            "wal_after": wal_file_size(db_path),
            "wal_peak": cleanup["wal_peak"],
            "chunks": cleanup["chunks"],
        }
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def delete_owner_from_sqlite(db_path, owner_mid, vacuum=True, progress_callback=None):
    owner_mid = str(owner_mid or "").strip()
    if not owner_mid:
        raise ValueError("请选择要删除的 UP 主")

    conn = connect(db_path)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT bvid
            FROM videos
            WHERE owner_mid = ?
            ORDER BY fetched_at DESC
            """,
            (owner_mid,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise LookupError("没有找到这个 UP 主的本地视频")
    return delete_videos_from_sqlite(db_path, [row["bvid"] for row in rows], vacuum=vacuum, progress_callback=progress_callback)


def vacuum_database(db_path):
    db_path = Path(db_path)
    size_before = db_path.stat().st_size if db_path.exists() else 0
    wal_before = wal_file_size(db_path)
    checkpoint_database(db_path, truncate=True)
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    checkpoint_database(db_path, truncate=True)
    size_after = db_path.stat().st_size if db_path.exists() else 0
    return {
        "size_before": size_before,
        "size_after": size_after,
        "bytes_reclaimed": max(0, size_before - size_after),
        "wal_before": wal_before,
        "wal_after": wal_file_size(db_path),
    }


def wal_path_for(db_path):
    db_path = Path(db_path)
    return db_path.with_name(f"{db_path.name}-wal")


def wal_file_size(db_path):
    path = wal_path_for(db_path)
    return path.stat().st_size if path.exists() else 0


def checkpoint_database_if_large(db_path, threshold_bytes=DEFAULT_WAL_CHECKPOINT_THRESHOLD_BYTES):
    if wal_file_size(db_path) < threshold_bytes:
        return {
            "checkpointed": False,
            "wal_before": wal_file_size(db_path),
            "wal_after": wal_file_size(db_path),
        }
    return checkpoint_database(db_path, truncate=True)


def checkpoint_database(db_path, truncate=False):
    db_path = Path(db_path)
    wal_before = wal_file_size(db_path)
    conn = connect(db_path)
    try:
        mode = "TRUNCATE" if truncate else "PASSIVE"
        row = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
    finally:
        conn.close()
    return {
        "checkpointed": True,
        "mode": "TRUNCATE" if truncate else "PASSIVE",
        "busy": row[0] if row else 0,
        "log": row[1] if row else 0,
        "checkpointed_frames": row[2] if row else 0,
        "wal_before": wal_before,
        "wal_after": wal_file_size(db_path),
    }


def set_database_journal_mode(db_path, mode):
    conn = connect(db_path)
    try:
        row = conn.execute(f"PRAGMA journal_mode = {mode}").fetchone()
        conn.commit()
    finally:
        conn.close()
    return row[0] if row else ""


def delete_video_rows_chunked(db_path, bvids, progress_callback=None):
    db_path = Path(db_path)
    selected_bvids = [str(item).strip() for item in bvids if str(item).strip()]
    if not selected_bvids:
        return {"wal_before": wal_file_size(db_path), "wal_peak": wal_file_size(db_path), "chunks": 0}

    wal_before = wal_file_size(db_path)
    checkpoint_database(db_path, truncate=True)
    wal_peak = wal_file_size(db_path)
    chunks = 0
    set_database_journal_mode(db_path, "DELETE")
    conn = connect(db_path)
    try:
        ensure_schema(conn, journal_mode=None)
        deleted_user_mids = collect_comment_mids(conn, selected_bvids)
        while True:
            batch = fetch_comment_rpid_batch(conn, selected_bvids, DELETE_COMMENT_BATCH_SIZE)
            if not batch:
                break
            marks = placeholders(len(batch))
            conn.execute(f"DELETE FROM comment_pictures WHERE rpid IN ({marks})", batch)
            conn.execute(f"DELETE FROM comment_emotes WHERE rpid IN ({marks})", batch)
            conn.execute(f"DELETE FROM comments WHERE rpid IN ({marks})", batch)
            conn.commit()
            chunks += 1
            wal_peak = max(wal_peak, wal_file_size(db_path))
            conn.close()
            conn = None
            checkpoint = delete_mode_checkpoint(db_path)
            notify_delete_progress(progress_callback, "comments", chunks, wal_peak, checkpoint)
            conn = connect(db_path)

        while True:
            batch = fetch_scalar_batch(conn, "SELECT dmid FROM danmaku WHERE bvid IN ({marks}) LIMIT ?", selected_bvids, DELETE_DANMAKU_BATCH_SIZE)
            if not batch:
                break
            marks = placeholders(len(batch))
            conn.execute(f"DELETE FROM danmaku WHERE dmid IN ({marks})", batch)
            conn.commit()
            chunks += 1
            wal_peak = max(wal_peak, wal_file_size(db_path))
            conn.close()
            conn = None
            checkpoint = delete_mode_checkpoint(db_path)
            notify_delete_progress(progress_callback, "danmaku", chunks, wal_peak, checkpoint)
            conn = connect(db_path)

        for batch in chunked(selected_bvids, DELETE_VIDEO_BATCH_SIZE):
            marks = placeholders(len(batch))
            conn.execute(f"DELETE FROM videos WHERE bvid IN ({marks})", batch)
            conn.commit()
            chunks += 1
            wal_peak = max(wal_peak, wal_file_size(db_path))
            conn.close()
            conn = None
            checkpoint = delete_mode_checkpoint(db_path)
            notify_delete_progress(progress_callback, "videos", chunks, wal_peak, checkpoint)
            conn = connect(db_path)

        cleanup_unreferenced_users(conn, deleted_user_mids)
        conn.commit()
        chunks += 1
        wal_peak = max(wal_peak, wal_file_size(db_path))
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
        set_database_journal_mode(db_path, "WAL")
    checkpoint_database(db_path, truncate=True)
    return {"wal_before": wal_before, "wal_peak": wal_peak, "chunks": chunks}


def delete_mode_checkpoint(db_path):
    return {
        "checkpointed": False,
        "wal_before": wal_file_size(db_path),
        "wal_after": wal_file_size(db_path),
    }


def notify_delete_progress(callback, stage, chunks, wal_peak, checkpoint):
    if not callback:
        return
    callback(
        {
            "stage": stage,
            "chunks": chunks,
            "wal_peak": wal_peak,
            "wal_after": checkpoint.get("wal_after", 0),
            "checkpointed": bool(checkpoint.get("checkpointed")),
        }
    )


def collect_comment_mids(conn, bvids):
    params = list(bvids)
    marks = placeholders(len(params))
    rows = conn.execute(f"SELECT DISTINCT mid FROM comments WHERE bvid IN ({marks}) AND mid IS NOT NULL AND mid != ''", params).fetchall()
    return [row["mid"] for row in rows]


def fetch_comment_rpid_batch(conn, bvids, limit):
    return fetch_scalar_batch(conn, "SELECT rpid FROM comments WHERE bvid IN ({marks}) LIMIT ?", bvids, limit)


def fetch_scalar_batch(conn, sql_template, bvids, limit):
    params = list(bvids)
    marks = placeholders(len(params))
    rows = conn.execute(sql_template.format(marks=marks), [*params, int(limit)]).fetchall()
    return [row[0] for row in rows]


def chunked(items, size):
    for index in range(0, len(items), size):
        yield list(items[index : index + size])


def delete_video_rows(conn, bvids):
    params = list(bvids)
    marks = placeholders(len(params))
    deleted_user_rows = conn.execute(f"SELECT DISTINCT mid FROM comments WHERE bvid IN ({marks}) AND mid IS NOT NULL AND mid != ''", params).fetchall()
    deleted_user_mids = [row["mid"] for row in deleted_user_rows]
    conn.execute(f"DELETE FROM comment_pictures WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN ({marks}))", params)
    conn.execute(f"DELETE FROM comment_emotes WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN ({marks}))", params)
    conn.execute(f"DELETE FROM comments WHERE bvid IN ({marks})", params)
    conn.execute(f"DELETE FROM danmaku WHERE bvid IN ({marks})", params)
    conn.execute(f"DELETE FROM videos WHERE bvid IN ({marks})", params)
    cleanup_unreferenced_users(conn, deleted_user_mids)


def cleanup_unreferenced_users(conn, mids=None):
    selected_mids = sorted({str(mid).strip() for mid in (mids or []) if str(mid).strip()})
    if not selected_mids:
        return
    marks = placeholders(len(selected_mids))
    conn.execute(
        f"""
        DELETE FROM users
        WHERE mid IN ({marks})
          AND NOT EXISTS (
              SELECT 1
              FROM comments
              WHERE comments.mid = users.mid
              LIMIT 1
          )
        """,
        selected_mids,
    )


def count_archive_rows(conn, bvids):
    params = list(bvids)
    marks = placeholders(len(params))
    return {
        "videos": len(params),
        "comments": conn.execute(f"SELECT COUNT(*) FROM comments WHERE bvid IN ({marks})", params).fetchone()[0],
        "comment_pictures": conn.execute(
            f"SELECT COUNT(*) FROM comment_pictures WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN ({marks}))",
            params,
        ).fetchone()[0],
        "comment_emotes": conn.execute(
            f"SELECT COUNT(*) FROM comment_emotes WHERE rpid IN (SELECT rpid FROM comments WHERE bvid IN ({marks}))",
            params,
        ).fetchone()[0],
        "danmaku": conn.execute(f"SELECT COUNT(*) FROM danmaku WHERE bvid IN ({marks})", params).fetchone()[0],
    }


def placeholders(count):
    return ",".join("?" for _ in range(count))


def video_delete_summary(row):
    return {
        "bvid": row["bvid"],
        "title": row["title"],
        "owner_mid": value_or_empty(row["owner_mid"]),
        "owner_name": row["owner_name"] or "",
    }


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
