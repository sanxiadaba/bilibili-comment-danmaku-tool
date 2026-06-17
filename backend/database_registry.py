import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from bilibili_comment_danmaku.archive import import_archive_json_to_sqlite, read_archive_meta
from bilibili_comment_danmaku.storage import connect, connect_readonly, ensure_schema, list_video_summaries_page
from errors import BadRequestError


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "comment_danmaku.db"
DEFAULT_DATABASE_DIR = ROOT / "data" / "databases"
DEFAULT_EXPORT_DIR = DEFAULT_DATABASE_DIR
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
IMPORT_EXTENSIONS = DATABASE_EXTENSIONS | {".json"}
AGGREGATE_VIDEO_LIST_LIMIT = 100000


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


def find_video_database_path(bvid, database_dir=DEFAULT_DATABASE_DIR):
    filename = video_database_filename(bvid)
    database_dir = Path(database_dir).resolve()
    if not database_dir.exists():
        return None
    matches = sorted(database_dir.rglob(filename), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    for match in matches:
        if match.is_file() and match.suffix.lower() in DATABASE_EXTENSIONS:
            return match.resolve()
    return None


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
    database_dir = Path(database_dir).resolve()
    if not database_dir.exists():
        return
    for path in sorted(database_dir.rglob("*"), key=lambda item: str(item.relative_to(database_dir)).lower()):
        if path.is_file() and path.suffix.lower() in DATABASE_EXTENSIONS:
            yield path.resolve(), f"db:{path.relative_to(database_dir).as_posix()}"


def list_all_video_summaries_page(main_db_path=DEFAULT_DB, database_dir=DEFAULT_DATABASE_DIR, limit=40, offset=0, include_owners=True):
    limit = max(1, min(int(limit or 40), 200))
    offset = max(0, int(offset or 0))
    by_bvid = {}
    for db_path, db_id in iter_catalog_database_paths(main_db_path, database_dir):
        if not Path(db_path).exists():
            continue
        try:
            page = list_video_summaries_page(
                db_path,
                limit=AGGREGATE_VIDEO_LIST_LIMIT,
                offset=0,
                include_owners=False,
            )
        except Exception:
            continue
        for video in page.get("videos") or []:
            item = {**video, "db_id": db_id}
            current = by_bvid.get(item["bvid"])
            if current is None or video_summary_rank(item, db_id) > video_summary_rank(current, current.get("db_id")):
                by_bvid[item["bvid"]] = item

    videos = sorted(by_bvid.values(), key=video_summary_sort_key, reverse=True)
    total = len(videos)
    selected = videos[offset : offset + limit]
    payload = {
        "videos": selected,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
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
        key = f"mid:{owner_mid}" if owner_mid else f"name:{owner_name}"
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

    for path in sorted(database_dir.rglob("*"), key=lambda item: str(item.relative_to(database_dir)).lower()):
        if not path.is_file() or path.suffix.lower() not in DATABASE_EXTENSIONS:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        databases.append(
            database_info_for_path(
                resolved,
                main_db_path,
                database_dir,
                db_id=f"db:{path.relative_to(database_dir).as_posix()}",
                role="hotplug",
                include_details=include_details,
            )
        )
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
    try:
        conn = connect(path) if include_details else connect_readonly(path)
        try:
            if include_details:
                ensure_schema(conn)
                conn.commit()
            archive_meta = read_archive_meta(conn)
            storage = database_storage_info(conn, path)
            row = database_counts(conn)
            bvid_rows = list_database_bvid_stats(conn) if include_details else list_database_bvid_stats_light(conn)
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
            top_owners = list_database_top_owners(conn) if include_details else []
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
    return conn.execute(
        """
        SELECT bvid, title, owner_mid, owner_name, fetched_at,
               (SELECT COUNT(*) FROM comments WHERE comments.bvid = videos.bvid) AS comment_count,
               (SELECT COUNT(*) FROM danmaku WHERE danmaku.bvid = videos.bvid) AS danmaku_count
        FROM videos
        ORDER BY fetched_at DESC, bvid
        LIMIT 2000
        """
    ).fetchall()


def list_database_bvid_stats_light(conn):
    return conn.execute(
        """
        SELECT bvid, title, owner_mid, owner_name, fetched_at,
               0 AS comment_count,
               0 AS danmaku_count
        FROM videos
        ORDER BY fetched_at DESC, bvid
        LIMIT 50
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
                    ELSE 'name:' || COALESCE(owner_name, '')
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
    info = database_info_for_path(source_path)
    if not info["ok"]:
        raise ValueError(f"不是可用的归档数据库：{info['error']}")
    database_dir.mkdir(parents=True, exist_ok=True)
    if is_path_inside(source_path, database_dir):
        return source_path
    target_path = unique_database_path(database_dir / normalize_database_filename(source_path.name))
    shutil.copy2(source_path, target_path)
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
    return f"{stem[:100]}{suffix}"


def normalize_path_component(name):
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(name or "")).strip("._-")
    return (stem or "archive")[:100]


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
