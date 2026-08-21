"""Structured JSON logging for all future modules.

Log records include UTC timestamp, level, component, message, and run_id
when one is bound. Secret-like extra keys are redacted.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any, Final

from quant_platform.core.config import Settings
from quant_platform.core.ids import new_run_id
from quant_platform.core.redact import redact_secret_text

_run_id: ContextVar[str | None] = ContextVar("quant_platform_run_id", default=None)

_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "database_url",
        "dsn",
        "access_key",
        "private_key",
    }
)

LOGGER_NAME = "quant_platform"


def get_run_id() -> str | None:
    return _run_id.get()


def bind_run_id(run_id: str) -> Token[str | None]:
    return _run_id.set(run_id)


def reset_run_id(token: Token[str | None]) -> None:
    _run_id.reset(token)


@contextmanager
def bound_run_id(run_id: str | None = None) -> Iterator[str]:
    """Bind a run_id for the current context; generate one if omitted."""
    value = run_id or new_run_id()
    token = bind_run_id(value)
    try:
        yield value
    finally:
        reset_run_id(token)


def _redact(key: str, value: Any) -> Any:
    if key.lower() in _SECRET_KEYS:
        return "[redacted]"
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


class JsonLogFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "component": record.name,
            "message": redact_secret_text(record.getMessage()),
        }
        run_id = getattr(record, "run_id", None) or get_run_id()
        if run_id:
            payload["run_id"] = run_id
        if record.exc_info:
            payload["exc_info"] = redact_secret_text(
                self.formatException(record.exc_info)
            )
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
                "message",
            }:
                continue
            payload[key] = _redact(key, value)
        return json.dumps(payload, default=str)


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "run_id", None) is None:
            bound = get_run_id()
            if bound is not None:
                record.run_id = bound
        return True


def configure_logging(settings: Settings | None = None) -> logging.Logger:
    """Configure the platform logger once. Safe to call repeatedly."""
    logger = logging.getLogger(LOGGER_NAME)
    level_name = (settings.log_level if settings is not None else "INFO").upper()
    logger.setLevel(level_name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        handler.addFilter(RunIdFilter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(component: str) -> logging.Logger:
    """Return a child logger under the platform namespace."""
    if component.startswith(LOGGER_NAME):
        return logging.getLogger(component)
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
