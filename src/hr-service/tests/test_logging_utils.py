"""Test JSON logging setup của hr-service (T3)."""
from __future__ import annotations

import json
import logging

import app.core.logging_utils as logging_utils
from app.core.logging_utils import JsonLogFormatter, configure_logging


def test_json_formatter_renders_one_line_json():
    fmt = JsonLogFormatter()
    record = logging.LogRecord(
        name="hr-service", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hr_audit intent=%s", args=("payroll",), exc_info=None,
    )
    line = fmt.format(record)
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "hr-service"
    assert payload["message"] == "hr_audit intent=payroll"
    assert "\n" not in line


def test_json_formatter_preserves_vietnamese_unicode():
    fmt = JsonLogFormatter()
    record = logging.LogRecord(
        name="hr-service", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="Bạn còn 8 ngày phép", args=(), exc_info=None,
    )
    payload = json.loads(fmt.format(record))
    assert payload["message"] == "Bạn còn 8 ngày phép"


def test_configure_logging_sets_level_and_is_idempotent():
    # reset cờ module để test deterministic, không phụ thuộc thứ tự import.
    logging_utils._configured = False
    root = logging.getLogger()
    try:
        configure_logging(logging.DEBUG)
        assert root.level == logging.DEBUG
        handlers_after_first = len(root.handlers)
        # Gọi lại: idempotent — không thêm handler mới.
        configure_logging(logging.INFO)
        assert len(root.handlers) == handlers_after_first
        # Level giữ nguyên DEBUG (lần đầu thắng, không reconfigure).
        assert root.level == logging.DEBUG
    finally:
        logging_utils._configured = False
