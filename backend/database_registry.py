"""数据库目录：解析 db_id、扫描 catalog、聚合视频列表、导入/导出路径。"""

import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from bilibili_comment_danmaku.archive import import_archive_json_to_sqlite, read_archive_meta
from bilibili_comment_danmaku.storage import (
    connect,
    connect_readonly,
    ensure_schema_if_needed,
    list_video_summaries_page,
    schema_is_current,
)
from errors import BadRequestError


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_DATABASE_DIR = ROOT / "data" / "databases"
# 导出目录必须和扫描根分开：导出副本落在 data/databases 下会被 catalog 当成一份新档案，
# 聚合视图里同一个视频因此出现两次，导出文件也会被 find_video_database_path 抢走。
DEFAULT_EXPORT_DIR = ROOT / "data" / "exports"
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
IMPORT_EXTENSIONS = DATABASE_EXTENSIONS | {".json"}


def resolve_database_path(db_id, main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR):
    db_id = (str(db_id or "main")).strip() or "main"
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    if db_id == "main":
        return main_db_path
    prefix, _, name = db_id.partition(":")
    if prefix != "db" or not name:
        raise BadRequestError("数据库标识无效")
    candidate = (database_dir / name.replace("\\", "/")).resolve()
    if not is_path_inside(candidate, database_dir):
        raise BadRequestError("数据库路径无效")
    if candidate.suffix.lower() not in DATABASE_EXTENSIONS:
        raise BadRequestError("只支持 .db / .sqlite / .sqlite3 数据库")
    if not candidate.exists():
        raise BadRequestError("数据库不存在，请刷新数据库列表")
    return candidate


def video_database_filename(bvid):
    bvid = str(bvid or "").strip()
    if not bvid:
        raise ValueError("missing bvid")
    return normalize_database_filename(f"{bvid}.db")


def owner_database_dir(owner_mid="", owner_name="", database_dir=DEFAULT_DATABASE_DIR):
    database_dir = Path(database_dir).resolve()
    owner_mid = str(owner_mid or "").strip()
    owner_name = str(owner_name or "").strip()
    if owner_name and owner_mid:
        label = f"{owner_name}_{owner_mid}"
    elif owner_name:
        label = owner_name
    elif owner_mid:
        label = f"mid_{owner_mid}"
    else:
        label = "unknown_owner"
    path = database_dir / normalize_path_component(label)
    path.mkdir(parents=True, exist_ok=True)
    return path


def video_database_path(bvid, database_dir=DEFAULT_DATABASE_DIR, owner_mid="", owner_name=""):
    return owner_database_dir(owner_mid, owner_name, database_dir) / video_database_filename(bvid)


def video_database_path_from_archive(archive, database_dir=DEFAULT_DATABASE_DIR):
    metadata = archive.get("metadata") or {}
    video_raw = archive.get("video_raw") or {}
    owner = video_raw.get("owner") or {}
    return video_database_path(
        metadata.get("bvid") or archive.get("bvid"),
        database_dir,
        owner_mid=owner.get("mid") or metadata.get("owner_mid") or "",
        owner_name=owner.get("name") or metadata.get("owner_name") or "",
    )


def iter_database_files(database_dir, filename=None):
    """Yield .db-style files under database_dir without following junctions or symlinks.

    A junction inside data/databases used to be scanned as if it were part of the archive, so a
    file outside the tree was listed as a hot-plug database (and migrated/refreshed in place).
    """
    database_dir = Path(database_dir).resolve()
    if not database_dir.exists():
        return
    # 导出目录如果被配置到扫描根里面，它的副本不是归档，不能参与 catalog 和查找。
    export_dir = _current_export_dir()
    exclude_export = export_dir != database_dir and is_path_inside(export_dir, database_dir)
    wanted = filename.lower() if filename else None
    for root, dirs, files in os.walk(database_dir):
        kept = []
        for name in sorted(dirs):
            candidate = Path(root) / name
            if candidate.is_symlink():
                continue
            if hasattr(os.path, "isjunction") and os.path.isjunction(candidate):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            if wanted is not None and name.lower() != wanted:
                continue
            path = Path(root) / name
            if path.suffix.lower() not in DATABASE_EXTENSIONS:
                continue
            if path.is_symlink():
                continue
            resolved = path.resolve()
            if not is_path_inside(resolved, database_dir):
                continue
            if exclude_export and is_path_inside(resolved, export_dir):
                continue
            yield resolved, f"db:{resolved.relative_to(database_dir).as_posix()}"


def _current_export_dir():
    """读取当前导出目录；测试可以替换 DEFAULT_EXPORT_DIR 而不必重载模块。"""
    try:
        return Path(DEFAULT_EXPORT_DIR).resolve()
    except OSError:
        return Path(DEFAULT_EXPORT_DIR)


def newest_database_path(matches):
    """Pick the most recently written database among duplicate archive copies."""
    candidates = []
    for item in matches or []:
        path = Path(item)
        try:
            if not path.is_file():
                continue
            candidates.append((path.stat().st_mtime_ns, path.resolve()))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def find_video_database_path(bvid, database_dir=DEFAULT_DATABASE_DIR):
    filename = video_database_filename(bvid)
    matches = [path for path, _db_id in iter_database_files(database_dir, filename)]
    return newest_database_path(matches)


VIDEO_SOURCE_STAT_SQL = """
SELECT videos.bvid,
       (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid) AS comment_count,
       (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS danmaku_count
FROM videos
WHERE videos.bvid IN (SELECT bvid FROM source_bvids)
"""

OWNER_VIDEO_SOURCE_STAT_SQL = """
SELECT videos.bvid,
       (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid) AS comment_count,
       (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS danmaku_count
FROM videos
WHERE videos.owner_mid = ?
"""


def _open_readonly(db_path):
    path = Path(db_path).resolve()
    if not path.exists() or not path.is_file():
        return None
    try:
        return connect_readonly(path)
    except Exception:
        return None


def database_video_stats(db_path, bvids=(), owner_mid=""):
    """Read per-video comment/danmaku counts from one database without mutating it.

    Returns a list of dicts with ``bvid``/``comment_count``/``danmaku_count``, or an empty list
    when the file is missing, corrupt, or belongs to an older schema.
    """
    bvids = [str(value).strip() for value in (bvids or []) if str(value).strip()]
    conn = _open_readonly(db_path)
    if conn is None:
        return []
    try:
        if owner_mid:
            rows = conn.execute(OWNER_VIDEO_SOURCE_STAT_SQL, (str(owner_mid),)).fetchall()
        else:
            if not bvids:
                return []
            conn.execute("DROP TABLE IF EXISTS source_bvids")
            conn.execute("CREATE TEMP TABLE source_bvids (bvid TEXT PRIMARY KEY)")
            conn.executemany("INSERT OR IGNORE INTO source_bvids (bvid) VALUES (?)", [(bvid,) for bvid in bvids])
            rows = conn.execute(VIDEO_SOURCE_STAT_SQL).fetchall()
        return [
            {
                "bvid": row["bvid"],
                "comment_count": int(row["comment_count"] or 0),
                "danmaku_count": int(row["danmaku_count"] or 0),
            }
            for row in rows
        ]
    except Exception:
        return []
    finally:
        conn.close()


def video_database_sources(bvids, database_dir=DEFAULT_DATABASE_DIR, fallback_db_path=None):
    """Resolve requested BVIDs to the per-video databases that hold them.

    Returns ``(sources, missing)`` where ``sources`` is ``[(db_path, [bvid, ...]), ...]``.
    ``fallback_db_path`` covers archives that still live in the legacy single-file database.
    """
    grouped = {}
    missing = []
    legacy_only = []
    # 一次扫描建好 {文件名小写: [路径]} 索引；按 bvid 逐个 find 会把整棵树走 N 遍。
    file_index = {}
    for path, _db_id in iter_database_files(database_dir):
        file_index.setdefault(path.name.lower(), []).append(path)
    for raw in bvids or []:
        bvid = str(raw).strip()
        if not bvid:
            continue
        path = newest_database_path(file_index.get(video_database_filename(bvid).lower(), ()))
        if path is None:
            legacy_only.append(bvid)
            continue
        bucket = grouped.setdefault(path, [])
        if bvid not in bucket:
            bucket.append(bvid)

    if legacy_only:
        found = {row["bvid"] for row in database_video_stats(fallback_db_path, bvids=legacy_only)} if fallback_db_path else set()
        for bvid in legacy_only:
            if bvid in found:
                legacy_path = Path(fallback_db_path).resolve()
                bucket = grouped.setdefault(legacy_path, [])
                if bvid not in bucket:
                    bucket.append(bvid)
            elif bvid not in missing:
                missing.append(bvid)
    return list(grouped.items()), missing


def owner_video_database_sources(owner_mid, database_dir=DEFAULT_DATABASE_DIR, fallback_db_path=None):
    """Resolve one UP's videos across every catalog database, newest copy winning ties."""
    owner_mid = str(owner_mid or "").strip()
    if not owner_mid:
        return []
    candidates = [Path(path).resolve() for path, _db_id in iter_catalog_database_paths(database_dir=database_dir)]
    if fallback_db_path:
        fallback = Path(fallback_db_path).resolve()
        if fallback.exists() and fallback not in candidates:
            candidates.append(fallback)

    best = {}
    for candidate in candidates:
        for row in database_video_stats(candidate, owner_mid=owner_mid):
            rank = (row["comment_count"], row["danmaku_count"])
            current = best.get(row["bvid"])
            if current is None or rank > current[0]:
                best[row["bvid"]] = (rank, candidate)

    grouped = {}
    for bvid in sorted(best):
        grouped.setdefault(best[bvid][1], []).append(bvid)
    return list(grouped.items())


def database_id_for_path(path, main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR):
    path = Path(path).resolve()
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    if path == main_db_path:
        return "main"
    if is_path_inside(path, database_dir):
        return f"db:{path.relative_to(database_dir).as_posix()}"
    return f"file:{path.name}"


def iter_catalog_database_paths(main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR):
    for path, db_id in iter_database_files(database_dir):
        yield path, db_id


def owner_key(owner_mid="", owner_name=""):
    """UP 主 owner key 的唯一构造规则：有 mid 用 mid，否则用清洗后的名字。

    storage.VIDEO_OWNER_KEY_SQL（SQL）和 owner_summaries_from_videos（Python）都必须走这里，
    否则同一个「没有 mid、名字为空」的 UP 会同时出现 ``name:`` 和 ``name:Unknown`` 两组。
    """
    owner_mid = str(owner_mid or "").strip()
    if owner_mid:
        return f"mid:{owner_mid}"
    return f"name:{str(owner_name or '').strip() or 'Unknown'}"


def video_owner_key(video):
    """Mirror of storage.VIDEO_OWNER_KEY_SQL for videos that came from several databases."""
    return owner_key(video.get("owner_mid"), video.get("owner_name"))


def video_matches_filters(video, query="", owner_key=""):
    needle = str(query or "").strip().lower()
    if needle:
        haystack = " ".join(
            [str(video.get("title") or ""), str(video.get("bvid") or ""), str(video.get("owner_name") or "")]
        ).lower()
        if needle not in haystack:
            return False
    owner_key = str(owner_key or "").strip()
    if owner_key and video_owner_key(video) != owner_key:
        return False
    return True


# 聚合视频列表的进程内缓存：单库按 (mtime, size) 命中，目录签名变化时回收旧条目。
# 每个请求都全量读所有库的视频是 P2-17 的开销来源；库文件没变就直接复用上一次的结果。
VIDEO_SUMMARY_CACHE_LOCK = threading.Lock()
_VIDEO_SUMMARY_CACHE = {}
_SUMMARY_DIRECTORY_SIGNATURES = {}


def database_file_token(path):
    """缓存令牌：主库和 WAL/journal 的时间戳与大小都要看。

    SQLite 的写入先落在 WAL 里，只比较主库 mtime 会把刚归档的视频当成旧缓存。
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    token = [stat.st_mtime_ns, stat.st_size]
    for suffix in ("-wal", "-journal"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        try:
            sidecar_stat = sidecar.stat()
        except OSError:
            token.extend([0, 0])
        else:
            # 只读连接也会建出 0 字节的 -wal/-shm；空的 sidecar 不代表数据变化。
            if sidecar_stat.st_size > 0:
                token.extend([sidecar_stat.st_mtime_ns, sidecar_stat.st_size])
            else:
                token.extend([0, 0])
    return tuple(token)


def _update_summary_directory_signature(database_dir, entries):
    """目录签名（文件列表 + 每个库的令牌）一旦变化，就先清掉该目录下失效的缓存。"""
    directory = str(Path(database_dir).resolve())
    signature = tuple((db_id, token) for _path, db_id, token in entries)
    current_paths = {str(Path(path).resolve()) for path, _db_id, _token in entries}
    with VIDEO_SUMMARY_CACHE_LOCK:
        if _SUMMARY_DIRECTORY_SIGNATURES.get(directory) == signature:
            return
        _SUMMARY_DIRECTORY_SIGNATURES[directory] = signature
        stale_keys = [
            key
            for key in _VIDEO_SUMMARY_CACHE
            if is_path_inside(key, directory) and key not in current_paths
        ]
        for key in stale_keys:
            _VIDEO_SUMMARY_CACHE.pop(key, None)


def _cached_database_videos(db_path, token=None):
    """单库视频列表缓存；``token`` 由调用方传入，避免同一请求重复 stat。"""
    key = str(Path(db_path).resolve())
    if token is None:
        token = database_file_token(db_path)
    if token is not None:
        with VIDEO_SUMMARY_CACHE_LOCK:
            cached = _VIDEO_SUMMARY_CACHE.get(key)
            if cached is not None and cached["token"] == token:
                return cached["videos"]
    # limit=None reads every video in the database; the per-request page size is applied
    # after merging, otherwise large databases silently lose everything past row 200.
    page = list_video_summaries_page(
        db_path,
        limit=None,
        offset=0,
        include_owners=False,
    )
    videos = list(page.get("videos") or [])
    if token is not None:
        with VIDEO_SUMMARY_CACHE_LOCK:
            _VIDEO_SUMMARY_CACHE[key] = {"token": token, "videos": videos}
    return videos


def clear_video_summary_cache():
    """清空聚合列表缓存（测试和需要强制重读的维护操作使用）。"""
    with VIDEO_SUMMARY_CACHE_LOCK:
        _VIDEO_SUMMARY_CACHE.clear()
        _SUMMARY_DIRECTORY_SIGNATURES.clear()


def list_all_video_summaries_page(
    main_db_path=DEFAULT_DB,
    database_dir=DEFAULT_DATABASE_DIR,
    limit=40,
    offset=0,
    include_owners=True,
    query="",
    owner_key="",
):
    limit = max(1, min(int(limit or 40), 200))
    offset = max(0, int(offset or 0))
    by_bvid = {}
    failed_databases = []
    entries = []
    for db_path, db_id in iter_catalog_database_paths(main_db_path, database_dir):
        if not Path(db_path).exists():
            continue
        entries.append((db_path, db_id, database_file_token(db_path)))
    _update_summary_directory_signature(database_dir, entries)
    for db_path, db_id, token in entries:
        try:
            videos = _cached_database_videos(db_path, token)
        except Exception as exc:
            # Keep going, but never pretend the aggregate is complete: the empty/partial list
            # used to look identical to "this database has no videos".
            failed_databases.append({"id": db_id, "error": str(exc)})
            continue
        for video in videos:
            item = {**video, "db_id": db_id}
            current = by_bvid.get(item["bvid"])
            if current is None or video_summary_rank(item, db_id) > video_summary_rank(current, current.get("db_id")):
                by_bvid[item["bvid"]] = item

    videos = sorted(by_bvid.values(), key=video_summary_sort_key, reverse=True)
    if query or owner_key:
        videos = [video for video in videos if video_matches_filters(video, query, owner_key)]
    total = len(videos)
    selected = videos[offset : offset + limit]
    payload = {
        "videos": selected,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
        "failed_databases": failed_databases,
        "complete": not failed_databases,
    }
    if include_owners:
        payload["owners"] = owner_summaries_from_videos(videos)
    return payload


def video_summary_rank(video, db_id):
    score = int(video.get("comment_total_count") or 0) * 10 + int(video.get("danmaku_count") or 0)
    if db_id and db_id != "main":
        score += 1
    return score


def video_summary_sort_key(video):
    return (str(video.get("fetched_at") or ""), str(video.get("bvid") or ""), str(video.get("db_id") or ""))


def owner_summaries_from_videos(videos):
    owners = {}
    for video in videos:
        owner_mid = str(video.get("owner_mid") or "")
        owner_name = str(video.get("owner_name") or "")
        key = owner_key(owner_mid, owner_name)
        current = owners.setdefault(
            key,
            {
                "key": key,
                "name": owner_name or "Unknown owner",
                "owner_mid": owner_mid,
                "video_count": 0,
                "comment_count": 0,
                "danmaku_count": 0,
            },
        )
        current["video_count"] += 1
        current["comment_count"] += int(video.get("comment_total_count") or 0)
        current["danmaku_count"] += int(video.get("danmaku_count") or 0)
    return sorted(
        owners.values(),
        key=lambda owner: (-owner["comment_count"], -owner["danmaku_count"], -owner["video_count"], owner["name"]),
    )


def list_database_catalog(main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR, include_details=True):
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    database_dir.mkdir(parents=True, exist_ok=True)
    databases = []
    seen = set()

    for path, db_id in iter_database_files(database_dir):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        info = database_info_for_path(
            resolved,
            main_db_path,
            database_dir,
            db_id=db_id,
            role="hotplug",
            include_details=include_details,
        )
        if not info.get("ok"):
            # An unreadable archive must not look like a healthy one in the list.
            info["coverage_status"] = "unreadable"
            info["coverage_message"] = info.get("error") or "数据库无法读取"
        databases.append(info)
    if include_details:
        annotate_database_coverage(databases)
    return [public_database_info(database) for database in databases]


def database_info_for_path(path, main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR, db_id=None, role=None, include_details=True):
    path = Path(path).resolve()
    main_db_path = Path(main_db_path).resolve()
    database_dir = Path(database_dir).resolve()
    if db_id is None:
        db_id = database_id_for_path(path, main_db_path, database_dir)
    if role is None:
        role = "main" if db_id == "main" else "hotplug"

    info = {
        "id": db_id,
        "role": role,
        "name": "主数据库" if db_id == "main" else path.stem,
        "file_name": path.name,
        "path": str(path),
        "relative_path": relative_to_root(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "page_count": 0,
        "page_size": 0,
        "freelist_count": 0,
        "reclaimable_bytes": 0,
        "used_bytes": 0,
        "wal_bytes": sidecar_file_size(path, "-wal"),
        "storage_message": "",
        "video_count": 0,
        "comment_count": 0,
        "danmaku_count": 0,
        "owner_count": 0,
        "top_owners": [],
        "archive_kind": "main" if db_id == "main" else "unknown",
        "archive_label": "主数据库" if db_id == "main" else "",
        "owner_mid": "",
        "owner_name": "",
        "bvids": [],
        "bvid_stats": [],
        "coverage_status": "unique",
        "coverage_message": "",
        "overlap_count": 0,
        "duplicate_database_ids": [],
        "better_database_ids": [],
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else "",
        "ok": False,
        "error": "",
    }
    if not path.exists():
        info["error"] = "文件不存在"
        return info
    if include_details and path.stat().st_size == 0:
        # Reading the catalog must not create a schema in an empty file; report it instead.
        info["error"] = "空文件（0 字节），不是有效的归档库"
        info["coverage_status"] = "unreadable"
        info["coverage_message"] = info["error"]
        return info
    try:
        conn = connect(path) if include_details else connect_readonly(path)
        try:
            if include_details:
                ensure_schema_if_needed(conn)
                conn.commit()
            archive_meta = read_archive_meta(conn)
            if not include_details:
                # 轻量模式只 stat + 单条 COUNT：聚合视图只需要 video_count，
                # comment/danmaku/owner 全量计数和 bvid_stats/top_owners 都不查。
                light_row = conn.execute("SELECT COUNT(*) FROM videos").fetchone()
                info.update(
                    {
                        "video_count": int((light_row[0] if light_row else 0) or 0),
                        "archive_kind": archive_kind_from_meta_or_stats(archive_meta, [], info["role"]),
                        "archive_label": archive_label_from_meta_or_stats(archive_meta, [], path, db_id),
                        "owner_mid": str(archive_meta.get("owner_mid") or ""),
                        "owner_name": str(archive_meta.get("owner_name") or ""),
                        "ok": True,
                    }
                )
                return info
            storage = database_storage_info(conn, path)
            row = database_counts(conn)
            bvid_rows = list_database_bvid_stats(conn)
            bvid_stats = [
                {
                    "bvid": item["bvid"],
                    "title": item["title"] or "",
                    "owner_mid": item["owner_mid"] or "",
                    "owner_name": item["owner_name"] or "",
                    "fetched_at": item["fetched_at"] or "",
                    "comment_count": item["comment_count"] or 0,
                    "danmaku_count": item["danmaku_count"] or 0,
                }
                for item in bvid_rows
            ]
            top_owners = list_database_top_owners(conn)
            archive_kind = archive_kind_from_meta_or_stats(archive_meta, bvid_stats, info["role"])
            info.update(
                {
                    **storage,
                    "video_count": row["video_count"] or 0,
                    "comment_count": row["comment_count"] or 0,
                    "danmaku_count": row["danmaku_count"] or 0,
                    "owner_count": row["owner_count"] or 0,
                    "top_owners": top_owners,
                    "archive_kind": archive_kind,
                    "archive_label": archive_label_from_meta_or_stats(archive_meta, bvid_stats, path, db_id),
                    "owner_mid": str(archive_meta.get("owner_mid") or single_database_value("owner_mid", bvid_stats) or ""),
                    "owner_name": str(archive_meta.get("owner_name") or single_database_value("owner_name", bvid_stats) or ""),
                    "bvids": [item["bvid"] for item in bvid_stats],
                    "bvid_stats": bvid_stats,
                    "ok": True,
                }
            )
        finally:
            conn.close()
    except Exception as exc:
        info["error"] = str(exc)
    return info


def database_counts(conn):
    return conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM videos) AS video_count,
            (SELECT COUNT(*) FROM comments) AS comment_count,
            (SELECT COUNT(*) FROM danmaku) AS danmaku_count,
            (SELECT COUNT(DISTINCT owner_mid) FROM videos WHERE owner_mid IS NOT NULL AND owner_mid <> '') AS owner_count
        """
    ).fetchone()


def list_database_bvid_stats(conn):
    # Coverage/duplicate detection needs every video of the database; the old 2000 row cap made
    # large imported archives look partially covered.
    return conn.execute(
        """
        SELECT bvid, title, owner_mid, owner_name, fetched_at,
               (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid) AS comment_count,
               (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS danmaku_count
        FROM videos
        ORDER BY fetched_at DESC, bvid
        """
    ).fetchall()


def database_storage_info(conn, path):
    page_count = pragma_int(conn, "page_count")
    page_size = pragma_int(conn, "page_size")
    freelist_count = pragma_int(conn, "freelist_count")
    reclaimable_bytes = max(0, freelist_count * page_size)
    allocated_bytes = max(0, page_count * page_size)
    used_bytes = max(0, allocated_bytes - reclaimable_bytes)
    if reclaimable_bytes > 0:
        storage_message = f"可通过整理空间回收约 {reclaimable_bytes} 字节"
    else:
        storage_message = "数据库已整理，没有可回收空页；文件大小主要来自仍保留的数据和索引"
    return {
        "page_count": page_count,
        "page_size": page_size,
        "freelist_count": freelist_count,
        "reclaimable_bytes": reclaimable_bytes,
        "used_bytes": used_bytes,
        "wal_bytes": sidecar_file_size(path, "-wal"),
        "storage_message": storage_message,
    }


def list_database_top_owners(conn, limit=6):
    rows = conn.execute(
        """
        WITH owner_videos AS (
            SELECT
                CASE
                    WHEN owner_mid IS NOT NULL AND owner_mid <> '' THEN 'mid:' || owner_mid
                    ELSE 'name:' || COALESCE(NULLIF(owner_name, ''), 'Unknown')
                END AS owner_key,
                COALESCE(owner_mid, '') AS owner_mid,
                COALESCE(owner_name, '') AS owner_name,
                bvid
            FROM videos
        ),
        comment_counts AS (
            SELECT bvid, COUNT(*) AS comment_count
            FROM comments
            GROUP BY bvid
        ),
        danmaku_counts AS (
            SELECT bvid, COUNT(*) AS danmaku_count
            FROM danmaku
            GROUP BY bvid
        )
        SELECT
            MAX(owner_mid) AS owner_mid,
            MAX(owner_name) AS owner_name,
            COUNT(*) AS video_count,
            COALESCE(SUM(comment_counts.comment_count), 0) AS comment_count,
            COALESCE(SUM(danmaku_counts.danmaku_count), 0) AS danmaku_count
        FROM owner_videos
        LEFT JOIN comment_counts ON comment_counts.bvid = owner_videos.bvid
        LEFT JOIN danmaku_counts ON danmaku_counts.bvid = owner_videos.bvid
        GROUP BY owner_key
        ORDER BY comment_count DESC, danmaku_count DESC, video_count DESC, owner_name ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [
        {
            "owner_mid": row["owner_mid"] or "",
            "owner_name": row["owner_name"] or "未知UP主",
            "video_count": row["video_count"] or 0,
            "comment_count": row["comment_count"] or 0,
            "danmaku_count": row["danmaku_count"] or 0,
        }
        for row in rows
    ]


def pragma_int(conn, name):
    row = conn.execute(f"PRAGMA {name}").fetchone()
    return int(row[0] or 0) if row else 0


def sidecar_file_size(path, suffix):
    sidecar = Path(path).with_name(f"{Path(path).name}{suffix}")
    return sidecar.stat().st_size if sidecar.exists() else 0


def public_database_info(info):
    public = dict(info)
    public.pop("bvid_stats", None)
    return public


def archive_kind_from_meta_or_stats(meta, bvid_stats, role):
    manifest = meta.get("manifest") if isinstance(meta.get("manifest"), dict) else {}
    kind = str(manifest.get("archive_kind") or meta.get("archive_kind") or "").strip()
    if kind in {"main", "up", "video", "collection", "unknown"}:
        return kind
    if role == "main":
        return "main"
    if len(bvid_stats) == 1:
        return "video"
    owner_mids = {item["owner_mid"] for item in bvid_stats if item["owner_mid"]}
    if len(bvid_stats) > 1 and len(owner_mids) == 1:
        return "up"
    if len(bvid_stats) > 1:
        return "collection"
    return "unknown"


def archive_label_from_meta_or_stats(meta, bvid_stats, path, db_id):
    manifest = meta.get("manifest") if isinstance(meta.get("manifest"), dict) else {}
    label = str(manifest.get("label") or meta.get("label") or "").strip()
    if label:
        return label
    if db_id == "main":
        return "主数据库"
    if len(bvid_stats) == 1:
        return bvid_stats[0]["title"] or bvid_stats[0]["bvid"]
    owner_names = {item["owner_name"] for item in bvid_stats if item["owner_name"]}
    if len(owner_names) == 1:
        return next(iter(owner_names))
    return Path(path).stem


def single_database_value(key, rows):
    values = {str(item.get(key) or "") for item in rows if item.get(key)}
    return next(iter(values)) if len(values) == 1 else ""


def annotate_database_coverage(databases):
    by_bvid = {}
    for database in databases:
        for item in database.get("bvid_stats") or []:
            by_bvid.setdefault(item["bvid"], []).append((database, item))

    for database in databases:
        if not database.get("ok"):
            continue
        bvids = database.get("bvids") or []
        overlaps = [bvid for bvid in bvids if len(by_bvid.get(bvid, [])) > 1]
        if not overlaps:
            database["coverage_status"] = "unique"
            database["coverage_message"] = "未发现同视频重复库"
            continue

        duplicate_ids = set()
        better_ids = set()
        same_count = 0
        for bvid in overlaps:
            peers = by_bvid.get(bvid, [])
            current_item = next((item for db, item in peers if db["id"] == database["id"]), None)
            if not current_item:
                continue
            current_score = database_video_score(current_item)
            peer_scores = [(db, item, database_video_score(item)) for db, item in peers if db["id"] != database["id"]]
            for peer_db, peer_item, peer_score in peer_scores:
                if peer_score == current_score:
                    duplicate_ids.add(peer_db["id"])
                    same_count += 1
                if peer_score > current_score:
                    better_ids.add(peer_db["id"])

        database["overlap_count"] = len(overlaps)
        database["duplicate_database_ids"] = sorted(duplicate_ids)
        database["better_database_ids"] = sorted(better_ids)
        if better_ids:
            database["coverage_status"] = "has_better"
            database["coverage_message"] = f"{len(overlaps)} 个视频与其它库重叠，其中有库的评论/弹幕更多"
        elif duplicate_ids and same_count >= len(overlaps):
            database["coverage_status"] = "duplicate"
            database["coverage_message"] = f"{len(overlaps)} 个视频与其它库内容相同或接近"
        else:
            database["coverage_status"] = "overlap"
            database["coverage_message"] = f"{len(overlaps)} 个视频也存在于其它数据库"


def database_video_score(item):
    return int(item.get("comment_count") or 0) * 10 + int(item.get("danmaku_count") or 0)


def inspect_importable_database(source_path):
    """只读校验一个待导入的数据库，返回 ``(ok, needs_migration, error)``。

    校验绝不能顺手迁移/改写源库：用户可能从只读目录或别的工具正在使用的文件导入。
    旧 schema 只报告 ``needs_migration``，由调用方在副本上迁移。
    """
    path = Path(source_path)
    if not path.exists() or not path.is_file():
        return False, False, "导入文件不存在"
    try:
        if path.stat().st_size == 0:
            return False, False, "空文件（0 字节），不是有效的归档库"
    except OSError as exc:
        return False, False, str(exc)
    conn = None
    try:
        conn = connect_readonly(path)
        if not schema_is_current(conn):
            return True, True, ""
        read_archive_meta(conn)
        conn.execute("SELECT COUNT(*) FROM videos").fetchone()
        return True, False, ""
    except Exception as exc:
        return False, False, str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def copy_database_file(source_path, target_path):
    """用 SQLite backup 复制数据库，确保 WAL 里尚未 checkpoint 的数据也进入副本。"""
    source_conn = connect_readonly(source_path)
    target_conn = sqlite3.connect(target_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def migrate_database_copy(db_path):
    """迁移一个副本（调用方保证它不是用户的源文件）。"""
    conn = connect(db_path)
    try:
        ensure_schema_if_needed(conn)
        conn.commit()
    finally:
        conn.close()


def import_database_file(source_path, database_dir=DEFAULT_DATABASE_DIR):
    source_path = Path(source_path).expanduser().resolve()
    database_dir = Path(database_dir).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise LookupError("导入文件不存在")
    if source_path.suffix.lower() not in IMPORT_EXTENSIONS:
        raise ValueError("只支持 .db / .sqlite / .sqlite3 / .json 归档")
    if source_path.suffix.lower() == ".json":
        database_dir.mkdir(parents=True, exist_ok=True)
        target_path = unique_database_path(database_dir / normalize_database_filename(source_path.with_suffix(".db").name))
        import_archive_json_to_sqlite(source_path, target_path)
        return target_path
    ok, needs_migration, error = inspect_importable_database(source_path)
    if not ok:
        raise ValueError(f"不是可用的归档数据库：{error}")
    database_dir.mkdir(parents=True, exist_ok=True)
    if is_path_inside(source_path, database_dir):
        # 已经在归档目录里：不动源文件，旧 schema 交给后续 catalog 打开时按需迁移。
        return source_path
    target_path = unique_database_path(database_dir / normalize_database_filename(source_path.name))
    try:
        copy_database_file(source_path, target_path)
        if needs_migration:
            # 只迁移副本，源库保持原样。
            migrate_database_copy(target_path)
            migrated_ok, _still_stale, migrated_error = inspect_importable_database(target_path)
            if not migrated_ok:
                raise ValueError(f"数据库迁移失败：{migrated_error}")
    except Exception:
        remove_file_quietly(target_path)
        raise
    return target_path


def import_uploaded_database_file(filename, content, database_dir=DEFAULT_DATABASE_DIR):
    if not content:
        raise ValueError("上传文件为空")
    database_dir = Path(database_dir).resolve()
    database_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        source_path = unique_database_path(database_dir / normalize_database_filename(filename, allowed_extensions=IMPORT_EXTENSIONS))
        source_path.write_bytes(content)
        target_path = unique_database_path(database_dir / normalize_database_filename(source_path.with_suffix(".db").name))
        try:
            import_archive_json_to_sqlite(source_path, target_path)
            return target_path
        finally:
            remove_file_quietly(source_path)
    target_path = unique_database_path(database_dir / normalize_database_filename(filename))
    target_path.write_bytes(content)
    try:
        info = database_info_for_path(target_path, database_dir=database_dir)
        if not info["ok"]:
            raise ValueError(info["error"] or "不是可用的归档数据库")
        return target_path
    except Exception:
        remove_file_quietly(target_path)
        raise


def normalize_database_filename(name, allowed_extensions=DATABASE_EXTENSIONS):
    path = Path(name)
    suffix = path.suffix.lower() if path.suffix.lower() in allowed_extensions else ".db"
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", path.stem).strip("._-") or "archive"
    stem = stem[:100]
    if stem.split(".")[0].lower() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def normalize_path_component(name):
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(name or "")).strip("._-")
    stem = (stem or "archive")[:100]
    # Windows refuses CON/NUL/COM1… as file or directory names, so an owner named "aux"
    # would otherwise break archiving with a confusing OSError.
    if stem.split(".")[0].lower() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return stem


def parse_multipart_files(raw, content_type):
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        raise ValueError("请求不是有效的 multipart/form-data")
    boundary = match.group(1).encode("utf-8")
    marker = b"--" + boundary
    close_marker = marker + b"--"
    files = []
    cursor = 0
    while True:
        start = raw.find(marker, cursor)
        if start < 0:
            break
        start += len(marker)
        if raw[start : start + 2] == b"--":
            break
        if raw[start : start + 2] == b"\r\n":
            start += 2
        next_marker = raw.find(marker, start)
        next_close_marker = raw.find(close_marker, start)
        candidates = [value for value in (next_marker, next_close_marker) if value >= 0]
        if not candidates:
            break
        end = min(candidates)
        part = raw[start:end]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        cursor = end
        if not part or b"\r\n\r\n" not in part:
            continue
        header_bytes, content = part.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("utf-8", errors="replace")
        disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if not filename_match:
            continue
        filename = Path(filename_match.group(1).replace("\\", "/")).name
        if filename:
            files.append({"filename": filename, "content": content})
    if not files:
        raise ValueError("没有收到文件")
    return files


def remove_file_quietly(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def unique_database_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time() * 1000)}{path.suffix}")


def is_path_inside(path, directory):
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False


def relative_to_root(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(path).resolve())


def export_database_path(label, export_dir=DEFAULT_EXPORT_DIR, suffix=".db"):
    export_dir = Path(export_dir).resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    suffix = suffix if suffix in {".db", ".json"} else ".db"
    safe_label = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(label or "archive")).strip("._-")
    safe_label = safe_label[:80] or "archive"
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    base_path = export_dir / f"{safe_label}_{timestamp}{suffix}"
    if not base_path.exists():
        return base_path
    for index in range(2, 1000):
        candidate = export_dir / f"{safe_label}_{timestamp}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return export_dir / f"{safe_label}_{timestamp}_{int(time.time() * 1000)}{suffix}"
