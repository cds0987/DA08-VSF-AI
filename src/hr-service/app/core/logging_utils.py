"""Structured (JSON) logging cho hr-service — đồng nhất với rag-worker (T3).

Trước đây hr-service dùng `logging.basicConfig` (format text), khác rag-worker
(JSON). Module này cung cấp `configure_logging` idempotent: gắn StreamHandler ra
stdout với JSON formatter ở root logger, đọc level từ tham số (gọi 1 lần ở
composition root / main). Chỉ stdlib, không phụ thuộc lib ngoài.
"""

from __future__ import annotations

import json
import logging
import sys


class JsonLogFormatter(logging.Formatter):
    """Render LogRecord thành một dòng JSON ra stdout (docker logs đọc được)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Bật JSON logging ra stdout ở root logger. Idempotent — gọi ở main."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    # Gỡ handler mặc định (nếu có) để tránh double-log / format text lẫn JSON.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
