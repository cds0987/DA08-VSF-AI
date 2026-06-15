"""Thin client (TÙY CHỌN) — helper cho service muốn gọi gateway bằng OpenAI SDK.

MOSA: service KHÔNG bắt buộc dùng cái này; chỉ cần trỏ base_url + OpenAI SDK là đủ.
Helper chỉ để tiện (PLAN §1b).
"""
from __future__ import annotations

from openai import AsyncOpenAI


def gateway_client(base_url: str, internal_token: str = "internal", timeout: float = 60.0) -> AsyncOpenAI:
    """AsyncOpenAI trỏ vào AI Router. `model` truyền vào = alias capability (answer/ocr/embed...)."""
    return AsyncOpenAI(base_url=base_url.rstrip("/"), api_key=internal_token,
                       timeout=timeout, max_retries=0)
