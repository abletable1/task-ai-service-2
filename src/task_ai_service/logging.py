"""Structured logs contain metadata only, never prompts, tokens or response bodies."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": request_id.get(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("task_ai_service")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    # HTTP client INFO logs can contain request URLs; application logs suffice.
    logging.getLogger("httpx").setLevel(logging.WARNING)
