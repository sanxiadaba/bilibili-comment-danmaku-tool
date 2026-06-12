import re
import threading
from datetime import datetime, timezone

from app_logging import log_event


progress_lock = threading.Lock()
progress_state = {
    "active": False,
    "kind": "",
    "bvid": "",
    "message": "",
    "logs": [],
    "percent": 0,
    "stage": "",
    "stats": {},
    "started_at": "",
    "updated_at": "",
    "done": False,
    "error": "",
}
queue_snapshot_provider = None


def set_queue_snapshot_provider(provider):
    global queue_snapshot_provider
    queue_snapshot_provider = provider


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def start_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        progress_state.update(
            {
                "active": True,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": [message],
                "percent": progress_percent(kind, message),
                "stage": progress_stage(kind, message),
                "stats": progress_stats(kind, message, {}),
                "started_at": now,
                "updated_at": now,
                "done": False,
                "error": "",
            }
        )
    log_event(
        "progress.start",
        message,
        kind=kind,
        bvid=bvid or "",
        percent=progress_percent(kind, message),
        stage=progress_stage(kind, message),
    )


def update_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        logs = [*progress_state.get("logs", []), message][-80:]
        stats = progress_stats(kind, message, progress_state.get("stats", {}))
        progress_state.update(
            {
                "active": True,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": progress_percent(kind, message, progress_state.get("percent", 0)),
                "stage": progress_stage(kind, message),
                "stats": stats,
                "updated_at": now,
                "done": False,
                "error": "",
            }
        )
        percent = progress_state.get("percent", 0)
        stage = progress_state.get("stage", "")
        stats = dict(progress_state.get("stats", {}))
    log_event("progress.update", message, kind=kind, bvid=bvid or "", percent=percent, stage=stage, stats=stats)


def finish_progress(kind, bvid, message):
    now = utc_now()
    with progress_lock:
        logs = [*progress_state.get("logs", []), message][-80:]
        progress_state.update(
            {
                "active": False,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": 100,
                "stage": "完成",
                "stats": progress_state.get("stats", {}),
                "updated_at": now,
                "done": True,
                "error": "",
            }
        )
    log_event("progress.finish", message, kind=kind, bvid=bvid or "", percent=100, stage="完成")


def fail_progress(kind, bvid, message):
    now = utc_now()
    stage = progress_stage(kind, message)
    with progress_lock:
        logs = [*progress_state.get("logs", []), f"失败：{message}"][-80:]
        progress_state.update(
            {
                "active": False,
                "kind": kind,
                "bvid": bvid or "",
                "message": message,
                "logs": logs,
                "percent": progress_state.get("percent", 0),
                "stage": stage,
                "stats": progress_state.get("stats", {}),
                "updated_at": now,
                "done": True,
                "error": message,
            }
        )
        percent = progress_state.get("percent", 0)
    log_event("progress.fail", message, kind=kind, bvid=bvid or "", percent=percent, stage=stage, level="error")


def get_progress_snapshot():
    with progress_lock:
        snapshot = {
            **progress_state,
            "logs": list(progress_state.get("logs", [])),
            "stats": dict(progress_state.get("stats", {})),
        }
    snapshot["queue"] = queue_snapshot_provider() if queue_snapshot_provider else {}
    return snapshot


def make_progress_logger(kind, bvid, logs):
    def log(message):
        logs.append(message)
        update_progress(kind, bvid, message)

    return log


def progress_stage(kind, message):
    if "HTTP 412" in message or "HTTP 429" in message or "cooling down" in message:
        return "接口冷却"
    if kind == "space" and ("暂停" in message or "暂不可用" in message):
        return "暂停归档"
    if kind == "space" and "UP视频失败" in message:
        return "跳过失败视频"
    if "失败" in message:
        return "失败"
    if "保存" in message:
        return "保存档案"
    if "likes" in message or "点赞" in message:
        return "弹幕点赞"
    if "parsed xml" in message:
        return "解析弹幕"
    if "fetching xml" in message or "正在重新抓取弹幕" in message or "正在抓取弹幕" in message:
        return "抓取弹幕"
    if message.startswith("main page"):
        return "抓取主评论"
    if "fetching children" in message or "children done" in message or "child root" in message:
        return "抓取楼中楼"
    if kind == "space":
        if "视频列表" in message:
            return "读取UP视频"
        if "保存评论" in message or "保存弹幕" in message:
            return "保存档案"
        if "弹幕" in message or "fetching xml" in message or "parsed xml" in message:
            return "抓取弹幕"
        if "跳过" in message:
            return "跳过已完成"
        if "间隔" in message:
            return "等待下一条"
        return "归档UP视频"
    if "评论抓取完成" in message:
        return "保存评论"
    if kind == "parse" and "准备解析" in message:
        return "解析视频"
    return "进行中"


def progress_percent(kind, message, current=0):
    if kind == "space":
        if "UP 主归档完成" in message:
            return 100
        if "视频列表" in message:
            return max(current, 5)
        index, total = parse_space_progress(message)
        if total:
            return max(current, min(99, 5 + int((index / total) * 94)))
        return max(current, 8)
    if "完成" in message:
        return 100
    if "保存" in message:
        return max(current, 92)
    if kind == "danmaku":
        if "fetching xml" in message:
            return max(current, 20)
        if "parsed xml" in message:
            return max(current, 45)
        batch = re.search(r"batch\s+(\d+)", message)
        if batch:
            return max(current, min(90, 55 + int(batch.group(1)) * 10))
        if "got=" in message:
            return max(current, 88)
    if kind == "parse":
        if message.startswith("main page"):
            page = parse_progress_int(message, r"main page\s+(\d+)")
            return max(current, min(55, 8 + page))
        if "child root" in message or "fetching children" in message or "children done" in message:
            index, total = parse_child_root_progress(message)
            if total:
                return max(current, min(76, 56 + int((index / total) * 20)))
            return max(current, min(76, current + 1))
        if "正在抓取弹幕" in message:
            return max(current, 78)
        if "danmaku likes" in message:
            return max(current, min(94, current + 4))
    if kind == "comments":
        if message.startswith("main page"):
            page = parse_progress_int(message, r"main page\s+(\d+)")
            return max(current, min(65, 10 + page))
        if "child root" in message or "fetching children" in message or "children done" in message:
            index, total = parse_child_root_progress(message)
            if total:
                return max(current, min(90, 66 + int((index / total) * 24)))
            return max(current, min(90, current + 2))
        if "评论抓取完成" in message:
            return max(current, 92)
    return max(current, 8)


def progress_stats(kind, message, current):
    stats = dict(current or {})
    if kind in {"comments", "parse"}:
        main = re.search(r"main page\s+(\d+): got=(\d+) unique=(\d+) all_count=([^ ]+)", message)
        if main:
            stats["主评论页"] = main.group(1)
            stats["本页评论"] = main.group(2)
            stats["已抓评论"] = main.group(3)
            if main.group(4) != "None":
                stats["接口总数"] = main.group(4)
        child_batch = re.search(r"fetching children batch: roots=(\d+) workers=(\d+) total_fetched=(\d+) total_expected=(\d+)", message)
        if child_batch:
            stats["楼中楼进度"] = f"0 / {child_batch.group(1)}"
            stats["楼中楼总已抓"] = child_batch.group(3)
            stats["楼中楼预期总数"] = child_batch.group(4)
            stats["并发数"] = child_batch.group(2)
        child_done = re.search(
            r"children done\s+(\d+)/(\d+)\s+root=([^ ]+)\s+fetched=(\d+)\s+total_fetched=(\d+)\s+total_expected=(\d+)",
            message,
        )
        if child_done:
            stats["楼中楼进度"] = f"{child_done.group(1)} / {child_done.group(2)}"
            stats["当前根评论"] = child_done.group(3)
            stats["当前楼中楼已抓"] = child_done.group(4)
            stats["楼中楼总已抓"] = child_done.group(5)
            stats["楼中楼预期总数"] = child_done.group(6)
        child = re.search(r"child root=.*?unique=(\d+).*?(?:expected|count)=(\d+|None)", message)
        if child:
            stats["当前楼中楼已抓"] = child.group(1)
            if child.group(2) != "None":
                stats["当前楼中楼预期"] = child.group(2)
        child_start = re.search(r"fetching children\s+(\d+)/(\d+)\s+root=([^ ]+)\s+expected=(\d+|None)", message)
        if child_start:
            stats["楼中楼进度"] = f"{child_start.group(1)} / {child_start.group(2)}"
            stats["当前根评论"] = child_start.group(3)
            if child_start.group(4) != "None":
                stats["当前楼中楼预期"] = child_start.group(4)
    if kind in {"danmaku", "parse"}:
        parsed = re.search(r"parsed xml items=(\d+)", message)
        if parsed:
            stats["弹幕条数"] = parsed.group(1)
        got = re.search(r"danmaku: cid=.*? got=(\d+)", message)
        if got:
            stats["弹幕条数"] = got.group(1)
        batch = re.search(r"danmaku likes: batch\s+(\d+) ids=(\d+)", message)
        if batch:
            stats["点赞批次"] = batch.group(1)
            stats["本批 dmid"] = batch.group(2)
    if kind == "space":
        list_done = re.search(r"UP视频列表完成 total=(\d+) complete=(\d+) archived=(\d+) skipped=(\d+)(?: failed=(\d+))?", message)
        if list_done:
            stats["UP视频总数"] = list_done.group(1)
            stats["已完成视频"] = list_done.group(2)
            stats["本次新增"] = list_done.group(3)
            stats["跳过视频"] = list_done.group(4)
            stats["失败视频"] = list_done.group(5) or "0"
        video = re.search(
            r"UP视频(?:抓取|跳过|失败)\s+(\d+)/(\d+).*?complete=(\d+).*?archived=(\d+).*?skipped=(\d+)(?:.*?failed=(\d+))?.*?bvid=([^ ]*)",
            message,
        )
        if video:
            stats["UP视频进度"] = f"{video.group(1)} / {video.group(2)}"
            stats["UP视频总数"] = video.group(2)
            stats["已完成视频"] = video.group(3)
            stats["本次新增"] = video.group(4)
            stats["跳过视频"] = video.group(5)
            if video.group(6) is not None:
                stats["失败视频"] = video.group(6)
            if video.group(7):
                stats["当前视频"] = video.group(7)
        interval = re.search(r"UP视频间隔\s+(\d+)/(\d+)\s+seconds=([0-9.]+)\s+next=(\d+)", message)
        if interval:
            stats["UP视频进度"] = f"{interval.group(1)} / {interval.group(2)}"
            stats["等待秒数"] = interval.group(3)
            stats["下一条序号"] = interval.group(4)
    return stats


def parse_progress_int(message, pattern):
    match = re.search(pattern, message)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def parse_child_root_progress(message):
    match = re.search(r"fetching children\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = re.search(r"children done\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def parse_space_progress(message):
    match = re.search(r"UP视频(?:抓取|跳过|失败|保存评论|保存弹幕|弹幕为空已跳过保存|间隔)\s+(\d+)/(\d+)", message)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def parse_float(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def first_int(*values):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def clamp_float(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def clamp_int(value, minimum, maximum):
    return max(minimum, min(maximum, value))
