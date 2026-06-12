import json
from datetime import datetime, timezone
from pathlib import Path


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
    except Exception:
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


def utc_now_text():
    return datetime.now(timezone.utc).astimezone().isoformat()
