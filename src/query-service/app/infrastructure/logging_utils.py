"""Structured logging tiện ích cho query-service.

Port pattern từ `src/rag-worker/core_engine/logging_utils.py` + thêm
`correlation_id_var` (ContextVar) để mỗi HTTP request gắn cùng ID xuyên suốt
log — kể cả log không qua `log_event` (middleware đặt contextvar, formatter tự đọc).

`configure_logging` bật JSON formatter ở root logger — gọi **một lần** trong lifespan
startup. Sau đó toàn bộ log của LangGraph nodes (đã có sẵn tên event) tự động
render ra JSON với correlation_id, không cần sửa từng call.

Không phụ thuộc thư viện ngoài — chỉ stdlib.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from time import perf_counter

# Contextvar lưu correlation_id của request hiện tại (task-local, async-safe).
# CorrelationIdMiddleware set giá trị; JsonLogFormatter đọc trong format().
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_EVENT_FIELDS_ATTR = "event_fields"

# Thuộc tính chuẩn của LogRecord — phần còn lại là `extra` trần (vd langgraph_act
# truyền extra={"tool":..., "intent":...} mà KHÔNG qua log_event) -> formatter tự gom.
_STD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"taskName", "event", _EVENT_FIELDS_ATTR}


class Stopwatch:
    """Đồng hồ wall-clock đơn giản dùng perf_counter.

        sw = Stopwatch()
        result = await do_something()
        log_event(logger, logging.INFO, "step_done", latency_ms=sw.elapsed_ms())
    """

    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = perf_counter()

    def reset(self) -> None:
        self._start = perf_counter()

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self._start) * 1000.0, 3)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


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
        # Gom các field `extra={}` trần (langgraph nodes dùng extra trực tiếp).
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_") and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Bật JSON logging ở root logger. Idempotent — gọi ở lifespan startup."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
