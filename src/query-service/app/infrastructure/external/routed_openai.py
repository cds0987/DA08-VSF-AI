"""Helper TẬP TRUNG dựng AsyncOpenAI *route-aware* cho các client phụ của query-service
(intent embed/LLM, guardrail judge, tool-decision, legacy streaming). Mọi LLM/embedding
PHẢI đi qua đây để route được ai-router (cân bằng key + cost-per-key + fallback) — xem
GATE ở tests/test_llm_architecture_enforcement.py.

CHỐT QUAN TRỌNG: LUÔN truyền base_url TƯỜNG MINH (kể cả None). Trước đây các client này tạo
`AsyncOpenAI(api_key=...)` KHÔNG base_url; SDK openai>=1.99 tự đọc env OPENAI_BASE_URL nên khi
prod set OPENAI_BASE_URL=http://ai-router:8010/v1 thì `responses.create` âm thầm bắn vào
`/v1/responses` — router KHÔNG có endpoint đó -> 404 -> guardrail fail-open câm + intent lỗi.
Nay các client route qua `chat.completions` với model = CAPABILITY name (router chọn model thật).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from app.infrastructure.config import Settings


def build_routed_openai(settings: Settings, *, timeout: float | None = None) -> tuple["AsyncOpenAI", bool]:
    """Trả (client, routing).

    routing=True khi OPENAI_BASE_URL set -> base_url=router, Bearer=AIROUTER_INTERNAL_TOKEN
    (router giữ key thật; fallback openai_api_key khi auth router off, vd e2e).
    routing=False -> base_url=None (direct OpenAI), Bearer=openai_api_key.
    """
    from openai import AsyncOpenAI

    routing = bool(settings.openai_base_url)
    api_key = (settings.airouter_internal_token or settings.openai_api_key or "") if routing \
        else (settings.openai_api_key or "")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=(settings.openai_base_url or None),
        timeout=timeout if timeout is not None else settings.openai_timeout_seconds,
    )
    return client, routing


def route_model(settings: Settings, capability: str, fallback_model: str) -> str:
    """model gửi cho SDK: route -> capability name (router map -> model thật); direct -> model thật."""
    return capability if settings.openai_base_url else fallback_model


def extract_json_text(content: str | None) -> str:
    """Lấy JSON từ message.content (chat.completions). Gỡ ```json fences nếu model bọc; rỗng -> '{}'."""
    s = (content or "").strip()
    if s.startswith("```"):
        if "\n" in s:
            s = s.split("\n", 1)[1]
        if "```" in s:
            s = s.rsplit("```", 1)[0]
    return s.strip() or "{}"
