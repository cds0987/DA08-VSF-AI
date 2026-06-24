"""Mô hình dữ liệu lõi: KeyEntry · ModelEntry · RouteDecision · Tier · capability config.

Tách 2 lớp (PLAN §15.1, §17):
- ModelEntry  = FACT của model (window/fee/is_free/tools/endpoint/modality) — auto-derive từ catalog.
- KeyEntry    = entitlement của 1 API key (provider/base_url/api_key_env/limit) — auto-discover từ env.
RouteDecision = kết quả resolve(): đúng 1 bộ (api_key, base_url, model_name) cho 1 request tại t.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Provider(str, Enum):
    OPENAI = "openai"
    OPENROUTER = "openrouter"


Endpoint = Literal["chat", "responses", "embeddings", "rerank"]
LimitKind = Literal["tokens_per_day", "requests_per_day", "budget_usd_per_day", "none"]


class Limit(BaseModel):
    """Giới hạn của 1 key. Kind khác nhau theo pool (PLAN §14.2)."""
    kind: LimitKind = "none"
    value: float = 0.0          # 2.5M tokens (openai) | 1000 req (openrouter free) | USD (paid)
    rpm: int | None = None      # requests/phút (OpenRouter free = 20)


class KeyEntry(BaseModel):
    """1 API key — đơn vị 'hấp thụ'. Auto-discover từ env theo pattern (PLAN §2)."""
    id: str                                  # "oai-1", "or-3"
    provider: Provider
    base_url: str | None = None              # None = OpenAI mặc định
    api_key_env: str                         # CHỈ tên env; giá trị key đọc lúc runtime
    tier: str                                # "free_oai" | "free_or" | "paid"
    limit: Limit = Field(default_factory=Limit)
    enabled: bool = True

    # Giá trị key thật — nạp riêng, KHÔNG serialize ra ngoài.
    def secret(self, env: dict[str, str]) -> str:
        return env.get(self.api_key_env, "")


class ModelEntry(BaseModel):
    """FACT của 1 model — từ model_catalog.json (build từ OpenRouter /models)."""
    id: str                                  # "openai/gpt-4o-mini"
    provider: str                            # "openai", "deepseek", ...
    name_native: str                         # "gpt-4o-mini"  (gọi trên OpenAI key)
    name_or: str                             # "openai/gpt-4o-mini" (gọi qua OpenRouter)
    context_length: int = 0
    price_in_per_mtok: float = 0.0           # USD / 1M token (giá gốc)
    price_out_per_mtok: float = 0.0
    price_in_with_fee: float = 0.0           # đã +phí nền tảng (nếu có)
    price_out_with_fee: float = 0.0
    is_free: bool = False
    supports_tools: bool = False
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    endpoint: Endpoint = "chat"

    def name_for(self, provider: Provider) -> str:
        """Provider-split (PLAN §5.4, đã verify): OpenAI=tên trần, OpenRouter=có provider."""
        return self.name_native if provider == Provider.OPENAI else self.name_or

    def is_vision(self) -> bool:
        return "image" in self.input_modalities


class RouteDecision(BaseModel):
    """Output của resolve() — cái client 'ngu' cần. PLAN §5.0."""
    key_id: str
    provider: Provider
    api_key: str                             # giá trị thật để dựng client
    base_url: str | None
    model_name: str                          # đã đúng dạng theo provider
    model_id: str                            # id catalog (để accounting/log)
    tier: str
    endpoint: Endpoint = "chat"
    # Token slot in-flight (selector elastic_banded) — router release sau khi call xong.
    # exclude=True: KHÔNG serialize ra response/log (nội bộ điều phối concurrency).
    inflight_token: str | None = Field(default=None, exclude=True)

    def public(self) -> dict:
        """Log/giám sát — KHÔNG lộ api_key."""
        return {
            "key_id": self.key_id, "provider": self.provider.value,
            "model": self.model_name, "tier": self.tier, "endpoint": self.endpoint,
        }


class Usage(BaseModel):
    """Token/cost thật sau call — để accounting (PLAN §5.7)."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # reasoning_tokens: phần reasoning của output (o-series/deepseek). LƯU Ý: đã NẰM TRONG
    # output_tokens (OpenAI completion_tokens gộp reasoning) -> KHÔNG cộng lại khi tính cost;
    # trường này chỉ để observability (tách phần reasoning).
    reasoning_tokens: int = 0
    cost_usd: float | None = None            # OpenRouter trả thật; OpenAI = None -> tự tính
    # cached_tokens: phần input ĐỌC TỪ CACHE (prompt caching DeepSeek/OpenAI tự động). Đã NẰM
    # TRONG input_tokens -> KHÔNG trừ khi tính cost; chỉ để observability đo cache hit rate.
    cached_tokens: int = 0
    cache_discount: float | None = None      # OpenRouter trả: tỉ lệ tiết kiệm nhờ cache (None nếu không)
