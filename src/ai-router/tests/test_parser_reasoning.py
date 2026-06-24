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


def test_extract_usage_cached_tokens_prompt_details():
    # Prompt caching (DeepSeek/OpenAI tự động): cached_tokens trong prompt_tokens_details.
    resp = {"usage": {
        "prompt_tokens": 1500,
        "completion_tokens": 200,
        "total_tokens": 1700,
        "prompt_tokens_details": {"cached_tokens": 1200},
        "cache_discount": 0.75,
    }}
    u = extract_usage(resp)
    assert u.cached_tokens == 1200            # 1200/1500 input đọc từ cache (hit)
    assert u.input_tokens == 1500             # cached ĐÃ nằm trong input -> KHÔNG trừ
    assert u.cache_discount == 0.75


def test_extract_usage_cache_defaults_zero_when_absent():
    resp = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    u = extract_usage(resp)
    assert u.cached_tokens == 0
    assert u.cache_discount is None
