from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_identity_var: ContextVar[str | None] = ContextVar(
    "authenticated_identity", default=None
)


def set_request_context(
    *,
    request_id: str | None = None,
    authenticated_identity: str | None = None,
) -> None:
    """Set request-scoped context values for structured logging."""
    _request_id_var.set(request_id)
    _identity_var.set(authenticated_identity)


def clear_request_context() -> None:
    """Clear request-scoped context values."""
    _request_id_var.set(None)
    _identity_var.set(None)


def get_request_id() -> str | None:
    """Return the active request ID, if any."""
    return _request_id_var.get()


def get_authenticated_identity() -> str | None:
    """Return the authenticated identity from the active request context."""
    return _identity_var.get()


@dataclass(slots=True)
class LogEvent:
    """Structured log payload."""

    message: str
    level: str
    logger: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds")
    )
    request_id: str | None = None
    authenticated_identity: str | None = None
    event: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    exc_info: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }
        if self.request_id:
            payload["request_id"] = self.request_id
        if self.authenticated_identity:
            payload["authenticated_identity"] = self.authenticated_identity
        if self.event:
            payload["event"] = self.event
        if self.exc_info:
            payload["exception"] = self.exc_info
        if self.extra:
            payload.update(self.extra)
        return payload


class JsonFormatter(logging.Formatter):
    """Format log records as newline-delimited JSON."""

    _reserved = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        request_id = getattr(record, "request_id", None) or get_request_id()
        authenticated_identity = (
            getattr(record, "authenticated_identity", None)
            or get_authenticated_identity()
        )
        event_name = getattr(record, "event", None)

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._reserved
            and key not in {"request_id", "authenticated_identity", "event"}
        }

        exc_text = None
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)

        log_event = LogEvent(
            message=message,
            level=record.levelname,
            logger=record.name,
            request_id=request_id,
            authenticated_identity=authenticated_identity,
            event=event_name,
            extra=extra,
            exc_info=exc_text,
        )
        return json.dumps(log_event.to_dict(), ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure application-wide structured logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for noisy_logger_name in ("uvicorn.access",):
        noisy_logger = logging.getLogger(noisy_logger_name)
        noisy_logger.handlers.clear()
        noisy_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger instance."""
    return logging.getLogger(name)
