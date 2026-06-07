import json
import logging
import queue
import sys
import traceback
import atexit
from datetime import datetime, timezone
from logging.handlers import QueueListener, RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4


LOGGER_NAME = "comment_danmaku"
_CONFIGURED = False
_STATE_LOCK = Lock()
_LOG_QUEUE = None
_QUEUE_LISTENER = None
_DROP_REPORT_INTERVAL_SECONDS = 60
_STATE = {
    "configured": False,
    "log_dir": "",
    "log_file": "",
    "level": "INFO",
    "max_bytes": 0,
    "backup_count": 0,
    "queue_max_size": 0,
    "dropped_count": 0,
    "dropped_by_level": {},
    "last_drop_at": "",
    "last_drop_reported_count": 0,
    "last_drop_report_at": 0.0,
    "started_at": "",
}


class SafeQueueListener(QueueListener):
    def enqueue_sentinel(self):
        while True:
            try:
                self.queue.put_nowait(self._sentinel)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    record_drop(logging.WARNING, "shutdown_drain")
                except queue.Empty:
                    continue


class BoundedQueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put_nowait(record)
        except queue.Full:
            if record.levelno >= logging.WARNING:
                self.try_make_room_for(record)
            else:
                record_drop(record.levelno, record.levelname)

    def try_make_room_for(self, record):
        try:
            self.log_queue.get_nowait()
            record_drop(logging.INFO, "evicted_for_warning")
            self.log_queue.put_nowait(record)
            return True
        except (queue.Empty, queue.Full):
            record_drop(record.levelno, "warning_drop_after_eviction")
            return False


class ResilientRotatingFileHandler(RotatingFileHandler):
    def handle(self, record):
        try:
            return super().handle(record)
        except Exception:
            record_drop(logging.ERROR, "file_handler_error")
            return False


class ResilientStreamHandler(logging.StreamHandler):
    def handle(self, record):
        try:
            return super().handle(record)
        except Exception:
            record_drop(logging.ERROR, "console_handler_error")
            return False


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


def configure_logging(
    log_dir,
    max_bytes=10 * 1024 * 1024,
    backup_count=10,
    queue_size=10000,
    level="INFO",
):
    global _CONFIGURED, _LOG_QUEUE, _QUEUE_LISTENER
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED:
        return logger

    log_dir = Path(log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    level_no = parse_level(level)
    max_bytes = max(0, int(max_bytes))
    backup_count = max(0, int(backup_count))
    queue_size = max(1, int(queue_size))

    logger.setLevel(level_no)
    logger.propagate = False
    logger.handlers.clear()

    file_handler = ResilientRotatingFileHandler(
        log_dir / "app.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level_no)
    file_handler.setFormatter(JsonLineFormatter())

    console_handler = ResilientStreamHandler(sys.stdout)
    console_handler.setLevel(level_no)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    _LOG_QUEUE = queue.Queue(maxsize=queue_size)
    _QUEUE_LISTENER = SafeQueueListener(_LOG_QUEUE, file_handler, console_handler, respect_handler_level=True)
    _QUEUE_LISTENER.start()
    logger.addHandler(BoundedQueueHandler(_LOG_QUEUE))

    with _STATE_LOCK:
        _STATE.update(
            {
                "configured": True,
                "log_dir": str(log_dir),
                "log_file": str(log_dir / "app.jsonl"),
                "level": logging.getLevelName(level_no),
                "max_bytes": max_bytes,
                "backup_count": backup_count,
                "queue_max_size": queue_size,
                "dropped_count": 0,
                "dropped_by_level": {},
                "last_drop_at": "",
                "last_drop_reported_count": 0,
                "last_drop_report_at": 0.0,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    _CONFIGURED = True
    atexit.register(shutdown_logging)
    return logger


def log_event(event, message="", level="info", **fields):
    logger = logging.getLogger(LOGGER_NAME)
    emit_drop_summary_if_due(logger)
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message or event, extra={"event_name": event, "event_data": clean_fields(fields)})


def log_exception(event, message="", **fields):
    logger = logging.getLogger(LOGGER_NAME)
    emit_drop_summary_if_due(logger)
    logger.exception(
        message or event,
        extra={"event_name": event, "event_data": clean_fields(fields)},
    )


def logging_status():
    listener = _QUEUE_LISTENER
    log_queue = _LOG_QUEUE
    with _STATE_LOCK:
        status = dict(_STATE)
        status["dropped_by_level"] = dict(_STATE["dropped_by_level"])
    status["queue_size"] = log_queue.qsize() if log_queue is not None else 0
    status["listener_alive"] = bool(
        listener is not None
        and getattr(listener, "_thread", None) is not None
        and listener._thread.is_alive()
    )
    return status


def shutdown_logging():
    global _QUEUE_LISTENER
    listener = _QUEUE_LISTENER
    if listener is None:
        return
    try:
        listener.stop()
    finally:
        _QUEUE_LISTENER = None


def new_request_id():
    return uuid4().hex[:12]


def parse_level(level):
    if isinstance(level, int):
        return level
    value = str(level or "INFO").upper()
    return getattr(logging, value, logging.INFO)


def record_drop(level_no, level_name):
    now = datetime.now(timezone.utc).isoformat()
    level_key = str(level_name or logging.getLevelName(level_no))
    with _STATE_LOCK:
        _STATE["dropped_count"] += 1
        _STATE["dropped_by_level"][level_key] = _STATE["dropped_by_level"].get(level_key, 0) + 1
        _STATE["last_drop_at"] = now


def emit_drop_summary_if_due(logger):
    now = monotonic()
    with _STATE_LOCK:
        dropped_count = _STATE["dropped_count"]
        if dropped_count <= _STATE["last_drop_reported_count"]:
            return
        if now - _STATE["last_drop_report_at"] < _DROP_REPORT_INTERVAL_SECONDS:
            return
        _STATE["last_drop_reported_count"] = dropped_count
        _STATE["last_drop_report_at"] = now
        dropped_by_level = dict(_STATE["dropped_by_level"])
    logger.warning(
        "logging queue overflow; some log records were dropped",
        extra={
            "event_name": "logging.queue_overflow",
            "event_data": clean_fields(
                {
                    "dropped_count": dropped_count,
                    "dropped_by_level": dropped_by_level,
                }
            ),
        },
    )


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
