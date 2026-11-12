"""Structured JSON logging using the standard library only."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "db_ms",
    "db_queries",
    "db_connect_ms",
    "db_connects",
    "tenant_id",
    "user_id",
    "event",
    "ip",
    # Shop assistant diagnostics. Never message content.
    "model",
    "error_code",
    "reason",
    "tool",
    # Daily backup email. Never addresses or file contents.
    "kind",
    "result",
    "file_bytes",
    "rows",
    "error",
    "sent",
    "failed",
    "skipped",
    "remaining",
    "configured",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Access logs are emitted by our own middleware, in the same JSON shape.
    logging.getLogger("uvicorn.access").disabled = True
