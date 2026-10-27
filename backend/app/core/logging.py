"""Structured JSON logging. Every line carries a timestamp, level, event name and the active request/run ids."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

http_request_id: ContextVar[str | None] = ContextVar("http_request_id", default=None)
client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
api_key_id: ContextVar[str | None] = ContextVar("api_key_id", default=None)

_logger = logging.getLogger("app")


def setup_logging(level: str = "INFO") -> None:
    if not _logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
        _logger.propagate = False
    _logger.setLevel(level.upper())


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    if not _logger.isEnabledFor(level):
        return
    record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "level": logging.getLevelName(level),
              "event": event}
    rid = http_request_id.get()
    if rid:
        record["http_request_id"] = rid
    record.update(fields)
    _logger.log(level, json.dumps(record, default=str, ensure_ascii=False))
