"""Structured logging tiện ích cho mcp-service.

Cùng pattern với query-service (port từ rag-worker logging_utils):
- `log_event` gắn field nghiệp vụ vào LogRecord.
- `JsonLogFormatter` render một dòng JSON kèm `correlation_id` từ contextvar —
  middleware ASGI set ID cho mỗi request, formatter tự đọc.
- `configure_logging` bật formatter ở root logger (idempotent, gọi 1 lần).
- `Stopwatch` đo latency per-call (ms).

Không phụ thuộc thư viện ngoài — chỉ stdlib.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from time import perf_counter

# Contextvar lưu correlation_id của request hiện tại (async-safe, task-local).
# CorrelationIdMiddleware (main.py) set giá trị; JsonLogFormatter đọc trong format().
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_EVENT_FIELDS_ATTR = "event_fields"


class Stopwatch:
    """Đồng hồ wall-clock đơn giản cho instrumentation per-call.

        sw = Stopwatch()
        result = await do_something()
        log_event(logger, logging.INFO, "call_done", latency_ms=sw.elapsed_ms())
    """

    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = perf_counter()

    def reset(self) -> None:
        self._start = perf_counter()

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self._start) * 1000.0, 3)


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    """Log một event có cấu trúc kèm các field nghiệp vụ."""
    extra = {"event": event, _EVENT_FIELDS_ATTR: tuple(fields), **fields}
    logger.log(level, event, extra=extra)


class JsonLogFormatter(logging.Formatter):
    """Render LogRecord thành một dòng JSON kèm correlation_id."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "correlation_id": correlation_id_var.get(),
        }
        for field in getattr(record, _EVENT_FIELDS_ATTR, ()):
            payload[field] = getattr(record, field, None)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Bật JSON logging ở root logger. Idempotent — gọi ở startup."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
