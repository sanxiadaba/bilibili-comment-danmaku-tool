CONTROL_API_VERSION = "v1"
CONTROL_NAMESPACE = "/api/v1/control"


DB_ID_SCHEMA = {
    "type": "string",
    "description": "Database id from /api/v1/control/databases. Omit or use main for the default database.",
    "default": "main",
}


CONTROL_ACTIONS = {
    "videos.parse": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/videos/parse",
        "description": "Fetch one video's comments and danmaku, then save them to the selected database.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "Bilibili video URL or BV id."},
                "video_ref": {"type": "string", "description": "Alias of url."},
                "bvid": {"type": "string", "description": "Alias of url when passing a BV id."},
                "db_id": DB_ID_SCHEMA,
                "delay": {"type": "number", "minimum": 0, "maximum": 5, "default": 0.35},
            },
        },
        "example": {"url": "BV1xx411c7mD", "db_id": "main", "delay": 0.35},
    },
    "comments.refresh": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/comments/refresh",
        "description": "Refresh one video's comments while preserving historical comments not returned this time.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["bvid"],
            "properties": {
                "bvid": {"type": "string", "description": "Target BV id."},
                "db_id": DB_ID_SCHEMA,
                "delay": {"type": "number", "minimum": 0, "maximum": 5, "default": 0.35},
            },
        },
        "example": {"bvid": "BV1xx411c7mD", "db_id": "main"},
    },
    "danmaku.refresh": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/danmaku/refresh",
        "description": "Refresh one video's danmaku. Empty remote results keep the existing local danmaku archive.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["bvid"],
            "properties": {
                "bvid": {"type": "string", "description": "Target BV id."},
                "db_id": DB_ID_SCHEMA,
            },
        },
        "example": {"bvid": "BV1xx411c7mD", "db_id": "main"},
    },
    "space.archive": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/space/archive",
        "description": "Queue a task that archives all videos from one Bilibili UP owner.",
        "async": True,
        "schema": {
            "type": "object",
            "required": ["owner_ref"],
            "properties": {
                "owner_ref": {"type": "string", "description": "Bilibili space URL or owner mid."},
                "url": {"type": "string", "description": "Alias of owner_ref."},
                "mid": {"type": "string", "description": "Alias of owner_ref when passing owner mid."},
                "db_id": DB_ID_SCHEMA,
                "delay": {"type": "number", "minimum": 0, "maximum": 5, "default": 1.0},
                "between_videos_min": {"type": "number", "minimum": 0, "maximum": 3600, "default": 8.0},
                "between_videos_max": {"type": "number", "minimum": 0, "maximum": 3600, "default": 20.0},
                "no_cache": {"type": "boolean", "default": False},
            },
        },
        "example": {"owner_ref": "https://space.bilibili.com/123456", "db_id": "main", "delay": 1.0},
    },
    "space.tasks.control": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/space/tasks/control",
        "description": "Pause, resume or stop queued UP-owner archive tasks. Omitting task_id applies to all current queue work.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["pause", "resume", "stop"]},
                "task_id": {"type": "string", "description": "Optional task id from /api/v1/control/progress."},
            },
        },
        "example": {"action": "pause"},
    },
    "archive.export": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/archive/export",
        "description": "Export selected videos or one UP owner archive. format=json only writes JSON; format=sqlite only writes SQLite.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["format"],
            "properties": {
                "format": {"type": "string", "enum": ["sqlite", "json"]},
                "bvid": {"type": "string", "description": "Export one video."},
                "bvids": {"type": "array", "items": {"type": "string"}, "description": "Export multiple videos."},
                "owner_mid": {"type": "string", "description": "Export all videos from one owner."},
                "db_id": DB_ID_SCHEMA,
                "label": {"type": "string", "description": "Output file label."},
            },
            "oneOf": [{"required": ["bvid"]}, {"required": ["bvids"]}, {"required": ["owner_mid"]}],
        },
        "example": {"format": "json", "bvid": "BV1xx411c7mD", "db_id": "main"},
    },
    "databases.import": {
        "method": "POST",
        "endpoint": f"{CONTROL_NAMESPACE}/databases/import",
        "description": "Import a local SQLite database or exported JSON archive by filesystem path.",
        "async": False,
        "schema": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Local .db/.sqlite/.sqlite3/.json path."},
                "source_path": {"type": "string", "description": "Alias of path."},
            },
        },
        "example": {"path": "D:/archives/video.json"},
    },
}


CONTROL_READ_ENDPOINTS = [
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/status", "description": "Control API status, progress and queue snapshot."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/databases", "description": "List available databases."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/videos", "description": "List local video summaries. Supports db_id."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/comments", "description": "Read comments. Supports bvid and db_id."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/danmaku", "description": "Read danmaku. Supports bvid, db_id and limit."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/progress", "description": "Read current fetch progress and task queue."},
    {"method": "GET", "endpoint": f"{CONTROL_NAMESPACE}/openapi.json", "description": "OpenAPI 3.1 document for control endpoints."},
]


def control_capabilities():
    return {
        "ok": True,
        "version": CONTROL_API_VERSION,
        "namespace": CONTROL_NAMESPACE,
        "actions_endpoint": f"{CONTROL_NAMESPACE}/actions",
        "openapi_endpoint": f"{CONTROL_NAMESPACE}/openapi.json",
        "actions": {
            name: {
                **definition,
                "params": params_from_schema(definition["schema"]),
            }
            for name, definition in CONTROL_ACTIONS.items()
        },
        "read_endpoints": CONTROL_READ_ENDPOINTS,
        "notes": [
            "This service is designed for local automation. Do not expose it directly to the public internet.",
            "External integrations should prefer /api/v1/control/* instead of UI-oriented /api/* paths.",
            "Long-running actions can be observed through /api/v1/control/progress or /api/v1/control/status.",
        ],
    }


def control_openapi_document():
    paths = {
        f"{CONTROL_NAMESPACE}/actions": {
            "post": {
                "summary": "Dispatch a control action",
                "requestBody": json_body_schema(
                    {
                        "type": "object",
                        "required": ["action"],
                        "properties": {
                            "action": {"type": "string", "enum": sorted(CONTROL_ACTIONS)},
                            "params": {"type": "object", "additionalProperties": True},
                        },
                    }
                ),
                "responses": default_responses(),
            }
        }
    }
    for action, definition in CONTROL_ACTIONS.items():
        paths[definition["endpoint"]] = {
            definition["method"].lower(): {
                "summary": action,
                "description": definition["description"],
                "requestBody": json_body_schema(definition["schema"]),
                "responses": default_responses(),
            }
        }
    for endpoint in CONTROL_READ_ENDPOINTS:
        if endpoint["endpoint"].endswith("/openapi.json"):
            continue
        paths[endpoint["endpoint"]] = {
            "get": {
                "summary": endpoint["description"],
                "responses": default_responses(),
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Bilibili Comment Danmaku Tool Control API",
            "version": CONTROL_API_VERSION,
            "description": "Stable local control API for automation and external integrations.",
        },
        "servers": [{"url": "http://127.0.0.1:8000"}],
        "paths": paths,
    }


def normalize_control_action_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Control action request body must be a JSON object")
    action = str(payload.get("action") or payload.get("type") or "").strip()
    if not action:
        raise ValueError("Missing action")
    if action not in CONTROL_ACTIONS:
        raise LookupError(f"Unsupported control action: {action}")
    params = payload.get("params")
    if params is None:
        params = payload.get("payload")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")
    return action, dict(params)


def params_from_schema(schema):
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    return [f"{name}{'' if name in required else '?'}" for name in properties]


def json_body_schema(schema):
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": schema,
            }
        },
    }


def default_responses():
    return {
        "200": {"description": "Success"},
        "202": {"description": "Accepted for queued work"},
        "400": {"description": "Invalid request"},
        "404": {"description": "Not found or unsupported action"},
        "409": {"description": "Another exclusive task is running"},
        "500": {"description": "Internal error"},
    }
