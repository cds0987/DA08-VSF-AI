"""Phase 4 — extract_usage bắt reasoning_tokens (o-series/deepseek) cho observability.

Chạy: python -m pytest tests/test_parser_reasoning.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.parser import extract_usage


def test_extract_usage_openai_reasoning_tokens():
    resp = {"usage": {
        "prompt_tokens": 27,
        "completion_tokens": 201,            # đã GỘP reasoning
        "total_tokens": 228,
        "completion_tokens_details": {"reasoning_tokens": 128},
    }}
    u = extract_usage(resp)
    assert u.input_tokens == 27
    assert u.output_tokens == 201            # KHÔNG trừ reasoning (tránh tính cost sai)
    assert u.reasoning_tokens == 128


def test_extract_usage_flat_reasoning_tokens():
    resp = {"usage": {"prompt_tokens": 10, "completion_tokens": 50, "reasoning_tokens": 20}}
    assert extract_usage(resp).reasoning_tokens == 20


def test_extract_usage_no_reasoning_defaults_zero():
    resp = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    assert extract_usage(resp).reasoning_tokens == 0
