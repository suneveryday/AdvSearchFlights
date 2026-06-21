from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER_NAME = "adv_search_flights"
_SENSITIVE_PARTS = ("proxy", "token", "cookie", "authorization", "password", "secret")


def log_path() -> Path:
    override = os.getenv("ADV_SEARCH_FLIGHTS_LOG_DIR")
    directory = Path(override).expanduser() if override else Path.home() / "Library" / "Logs" / "AdvSearchFlights"
    return directory / "app.log"


def configure_logging(*, force: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers and not force:
        return logger
    if force:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    configure_logging().log(level, event, extra={"diagnostic_fields": _sanitize(fields)})


def read_recent_logs(limit: int = 200) -> list[dict[str, Any]]:
    path = log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(limit), 2000)):]
    result: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {"message": line}
        result.append(item)
    return result


def _sanitize(value: Any, key: str = "") -> Any:
    if any(part in key.lower() for part in _SENSITIVE_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)[:500]}
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "diagnostic_fields", {}),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
