import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4


LOGGER_NAME = "comment_danmaku"
_CONFIGURED = False


class JsonLineFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
            "message": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update({key: value for key, value in event_data.items() if value is not None})
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_dir):
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED:
        return logger

    log_dir = Path(log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    file_handler = RotatingFileHandler(
        log_dir / "app.jsonl",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console_handler)

    _CONFIGURED = True
    return logger


def log_event(event, message="", level="info", **fields):
    logger = logging.getLogger(LOGGER_NAME)
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message or event, extra={"event_name": event, "event_data": clean_fields(fields)})


def log_exception(event, message="", **fields):
    logging.getLogger(LOGGER_NAME).exception(
        message or event,
        extra={"event_name": event, "event_data": clean_fields(fields)},
    )


def new_request_id():
    return uuid4().hex[:12]


def clean_fields(fields):
    return {key: sanitize_value(value) for key, value in fields.items() if value is not None}


def sanitize_value(value):
    if isinstance(value, dict):
        return {key: sanitize_value(item) for key, item in value.items() if not is_sensitive_key(key)}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item) for item in value[:50]]
    if isinstance(value, str):
        if len(value) > 500:
            return value[:500] + "...[truncated]"
        return value
    return value


def is_sensitive_key(key):
    lowered = str(key).lower()
    return any(marker in lowered for marker in ("cookie", "token", "password", "secret", "credential"))
