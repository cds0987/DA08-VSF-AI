"""Registry — auto-discover key từ env + định nghĩa tier (bậc thang cost). PLAN §2, §5.1.

Nguyên tắc: CHỈ đọc OPENAI_API_KEY_{n} và OPENROUTER_API_KEY_{n}. Mọi biến khác bỏ qua.
LOẠI `OPENAI_API_KEY` đơn (hệ cũ). Thêm key = thêm secret -> tự đăng ký, không sửa code.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from .schemas import KeyEntry, Limit, Provider

logger = logging.getLogger("ai_router.registry")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_RE_OPENAI = re.compile(r"^OPENAI_API_KEY_(\d+)$")
_RE_OPENROUTER = re.compile(r"^OPENROUTER_API_KEY_(\d+)$")

# Giới hạn mặc định/account (PLAN §13.2). Có thể override qua env.
OPENAI_TOKENS_PER_DAY = int(os.getenv("AIROUTER_OPENAI_TOKENS_PER_DAY", "2500000"))
OPENROUTER_REQ_PER_DAY = int(os.getenv("AIROUTER_OPENROUTER_REQ_PER_DAY", "1000"))
OPENROUTER_RPM = int(os.getenv("AIROUTER_OPENROUTER_RPM", "20"))


@dataclass(frozen=True)
class TierDef:
    """1 bậc thang. provider + bộ lọc model + chiều giới hạn áp lên mỗi key."""
    name: str
    provider: Provider
    model_free: bool | None       # True=chỉ free model · False=chỉ paid · None=mọi model (quota-based)
    limit_kind: str               # "tokens_per_day" | "requests_per_day" | "none"
    rpm: int | None               # trần RPM/key (None = không cap ở router)


# Bậc thang cost tăng dần (PLAN §5.1). OpenAI free = quota token; OpenRouter free = req/ngày; paid = OpenRouter trả phí.
# embed_oai riêng: embeddings tính phí TÁCH khỏi túi chat free 2.5M -> không cap token, chỉ track cost.
TIER_DEFS: dict[str, TierDef] = {
    "free_oai": TierDef("free_oai", Provider.OPENAI, None, "tokens_per_day", None),
    "free_or": TierDef("free_or", Provider.OPENROUTER, True, "requests_per_day", OPENROUTER_RPM),
    "paid": TierDef("paid", Provider.OPENROUTER, False, "none", OPENROUTER_RPM),
    "embed_oai": TierDef("embed_oai", Provider.OPENAI, None, "none", None),
}


def discover_keys(env: dict[str, str] | None = None) -> list[KeyEntry]:
    """Quét env -> KeyEntry. Chỉ pattern OPENAI_API_KEY_{n} / OPENROUTER_API_KEY_{n}."""
    env = env if env is not None else dict(os.environ)
    keys: list[KeyEntry] = []
    for name, value in env.items():
        if not value:
            continue
        if (m := _RE_OPENAI.match(name)):
            keys.append(KeyEntry(
                id=f"oai-{m.group(1)}", provider=Provider.OPENAI, base_url=None,
                api_key_env=name, tier="free_oai",
                limit=Limit(kind="tokens_per_day", value=OPENAI_TOKENS_PER_DAY),
            ))
        elif (m := _RE_OPENROUTER.match(name)):
            keys.append(KeyEntry(
                id=f"or-{m.group(1)}", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                api_key_env=name, tier="free_or",
                limit=Limit(kind="requests_per_day", value=OPENROUTER_REQ_PER_DAY, rpm=OPENROUTER_RPM),
            ))
    keys.sort(key=lambda k: k.id)
    logger.info("keys_discovered openai=%d openrouter=%d",
                sum(k.provider == Provider.OPENAI for k in keys),
                sum(k.provider == Provider.OPENROUTER for k in keys))
    return keys


class Registry:
    """Giữ danh sách key + giá trị secret + tier. Stateless về quota (quota ở counters/Redis)."""

    def __init__(self, keys: list[KeyEntry], env: dict[str, str] | None = None) -> None:
        self._keys = keys
        self._env = env if env is not None else dict(os.environ)
        self._by_id = {k.id: k for k in keys}

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Registry":
        env = env if env is not None else dict(os.environ)
        return cls(discover_keys(env), env)

    def secret(self, key: KeyEntry) -> str:
        return self._env.get(key.api_key_env, "")

    def get(self, key_id: str) -> KeyEntry | None:
        return self._by_id.get(key_id)

    def keys_for_provider(self, provider: Provider) -> list[KeyEntry]:
        """OpenRouter key phục vụ CẢ free_or lẫn paid (free vs paid model trên cùng key)."""
        return [k for k in self._keys if k.provider == provider and k.enabled]

    def all_keys(self) -> list[KeyEntry]:
        return list(self._keys)
