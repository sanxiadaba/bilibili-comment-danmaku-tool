CONTROL_API_VERSION = "v1"


CONTROL_ACTIONS = {
    "videos.parse": {
        "method": "POST",
        "endpoint": "/api/v1/control/videos/parse",
        "description": "抓取单个视频的评论和弹幕，并保存到指定数据库。",
        "params": ["url|video_ref|bvid", "db_id?", "delay?"],
    },
    "comments.refresh": {
        "method": "POST",
        "endpoint": "/api/v1/control/comments/refresh",
        "description": "刷新指定视频评论，保留本次未返回的历史评论。",
        "params": ["bvid", "db_id?", "delay?"],
    },
    "danmaku.refresh": {
        "method": "POST",
        "endpoint": "/api/v1/control/danmaku/refresh",
        "description": "刷新指定视频弹幕，空结果时保留已有弹幕档案。",
        "params": ["bvid", "db_id?"],
    },
    "space.archive": {
        "method": "POST",
        "endpoint": "/api/v1/control/space/archive",
        "description": "把 UP 主全部视频归档任务加入队列。",
        "params": ["owner_ref|url|mid", "db_id?", "delay?", "between_videos_min?", "between_videos_max?", "no_cache?"],
    },
    "archive.export": {
        "method": "POST",
        "endpoint": "/api/v1/control/archive/export",
        "description": "导出指定视频、视频集合或 UP 主归档。format=sqlite 只生成数据库，format=json 只生成 JSON。",
        "params": ["format=sqlite|json", "bvid?|bvids?|owner_mid?", "db_id?", "label?"],
    },
    "databases.import": {
        "method": "POST",
        "endpoint": "/api/v1/control/databases/import",
        "description": "从本机路径导入 SQLite 数据库或 JSON 归档。",
        "params": ["path|source_path"],
    },
}


CONTROL_READ_ENDPOINTS = [
    {"method": "GET", "endpoint": "/api/v1/control/status", "description": "控制面状态、进度和任务队列。"},
    {"method": "GET", "endpoint": "/api/v1/control/databases", "description": "列出可用数据库。"},
    {"method": "GET", "endpoint": "/api/v1/control/videos", "description": "列出视频摘要。支持 db_id。"},
    {"method": "GET", "endpoint": "/api/v1/control/comments", "description": "读取评论档案。支持 bvid、db_id。"},
    {"method": "GET", "endpoint": "/api/v1/control/danmaku", "description": "读取弹幕档案。支持 bvid、db_id、limit。"},
    {"method": "GET", "endpoint": "/api/v1/control/progress", "description": "读取当前抓取/队列进度。"},
]


def control_capabilities():
    return {
        "ok": True,
        "version": CONTROL_API_VERSION,
        "namespace": "/api/v1/control",
        "actions_endpoint": "/api/v1/control/actions",
        "actions": CONTROL_ACTIONS,
        "read_endpoints": CONTROL_READ_ENDPOINTS,
        "notes": [
            "服务默认面向本机工具调用，请不要直接暴露到公网。",
            "外部接口应优先使用 /api/v1/control/*，前端内部 /api/* 可能随 UI 演进调整。",
            "长耗时动作通过 /api/v1/control/progress 或 /api/v1/control/status 查询进度。",
        ],
    }


def normalize_control_action_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("控制动作请求体必须是 JSON 对象")
    action = str(payload.get("action") or payload.get("type") or "").strip()
    if not action:
        raise ValueError("缺少 action")
    if action not in CONTROL_ACTIONS:
        raise LookupError(f"不支持的控制动作：{action}")
    params = payload.get("params")
    if params is None:
        params = payload.get("payload")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是 JSON 对象")
    return action, dict(params)
