"""Structured logging tiện ích dùng chung.

`log_event` gắn các field nghiệp vụ vào LogRecord (qua `extra=`) — vừa để code đọc
trực tiếp `record.<field>`, vừa để `JsonLogFormatter` render ra JSON. `configure_logging`
bật formatter JSON ở root (gọi một lần ở composition root) để structured-log "active",
không chỉ "ready" (DAY0 §8). Không phụ thuộc thư viện ngoài — chỉ stdlib.
"""

from __future__ import annotations

import json
import logging
from time import perf_counter

# Thứ tự field chuẩn trong mỗi LogRecord do log_event tạo; formatter đọc list này
# để biết field nghiệp vụ nào cần serialize (tách khỏi attr built-in của LogRecord).
_EVENT_FIELDS_ATTR = "event_fields"


class Stopwatch:
    """Đồng hồ đo wall-clock đơn giản cho instrumentation per-stage.

    Dùng `perf_counter` (monotonic, độ phân giải cao) — KHÔNG phụ thuộc lib ngoài.
    Trả mili-giây vì đó là đơn vị các event log/benchmark dùng (đối chiếu eval p95).

        sw = Stopwatch()
        result = await do_stage()
        log_event(logger, logging.INFO, "stage_done", duration_ms=sw.elapsed_ms())
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
    """Log một event có cấu trúc. `event` là tên event; `fields` là context."""
    extra = {"event": event, _EVENT_FIELDS_ATTR: tuple(fields), **fields}
    logger.log(level, event, extra=extra)


class JsonLogFormatter(logging.Formatter):
    """Render LogRecord (kèm field của log_event) thành một dòng JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in getattr(record, _EVENT_FIELDS_ATTR, ()):  # type: ignore[arg-type]
            payload[field] = getattr(record, field, None)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Bật structured (JSON) logging ở root logger. Idempotent — gọi ở composition root."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
