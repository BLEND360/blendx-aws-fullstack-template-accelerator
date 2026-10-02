"""Structured logging: one JSON object per line, each carrying the request id.

    logger = get_logger(__name__)
    logger.info("item_created", item_id=item_id)
"""

import json
import logging
import os
import sys
from typing import Any

from app.core.context import get_request_id

# Never written, whatever a caller passes: logging is the easiest place to leak
# a credential by dumping a request body or a boto3 kwargs dict.
_REDACTED_KEYS = frozenset(
    {
        "authorization", "id_token", "access_token", "refresh_token", "token",
        "password", "secret", "api_key", "credentials",
    }
)

# Attributes every LogRecord has; anything else was attached by this module.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


def _redact(key: str, value: Any) -> Any:
    if key.lower() in _REDACTED_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _redact(k, v) for k, v in value.items()}
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(
            (k, v) for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        )
        if record.exc_info:
            # The traceback stays in the log; it never reaches a response body.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=repr, ensure_ascii=False)


_base_record_factory = logging.getLogRecordFactory()


def _record_with_request_id(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Stamps the request id on every record, third-party loggers' included."""
    record = _base_record_factory(*args, **kwargs)
    if request_id := get_request_id():
        record.request_id = request_id
    return record


def configure_logging() -> None:
    """Install the JSON handler on the root logger. Idempotent."""
    logging.setLogRecordFactory(_record_with_request_id)
    root = logging.getLogger()
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # The correlation middleware writes the access line, with the request id.
    logging.getLogger("uvicorn.access").disabled = True


class StructuredLogger:
    """`logger.info("event", key=value)`; keys that collide with LogRecord are prefixed."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, event: str, fields: dict[str, Any], exc_info: bool = False) -> None:
        extra = {(f"field_{k}" if k in _RESERVED else k): _redact(k, v) for k, v in fields.items()}
        self._logger.log(level, event, extra=extra, exc_info=exc_info)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, fields, exc_info=True)


configure_logging()


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name))
