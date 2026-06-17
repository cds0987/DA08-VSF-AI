"""Settings (env) + nạp routing.yaml (PLAN §13 config = file hot-reload, Redis cho counter)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIROUTER_", extra="ignore")

    redis_url: str | None = None                 # None -> dùng in-memory counter (dev/test)
    routing_path: str = "routing.yaml"
    catalog_path: str = "config/model_catalog.json"
    internal_token: str | None = None            # bảo vệ /v1/route, /admin
    request_timeout: float = 60.0
    # bật/tắt toàn bộ router; off -> caller tự xử (an toàn rollout, PLAN §8)
    enabled: bool = True
    # đọc usage thật từ provider lúc boot (OpenRouter /key) -> hết "mù 0". Off mặc định
    # (tránh chậm boot / lỗi mạng ở test); bật ở prod qua AIROUTER_RECONCILE_ON_BOOT=1.
    reconcile_on_boot: bool = False


class TierConfig(BaseModel):
    name: str                                    # "free_oai" | "free_or" | "paid"
    endpoint_default: str = "chat"


# --------------------------------------------------------------------------- #
# Selector params (MOSA) — mỗi selector tự validate self.params bằng model dưới.
# Thêm strategy mới = thêm 1 param-model ở đây, KHÔNG đụng khung config.
# --------------------------------------------------------------------------- #
class SaveModeConfig(BaseModel):
    """Save mode: khi MỌI tier cạn -> ép model rẻ (gpt-4o-mini) trên tier OpenAI,
    bỏ trần token free (daily_kind='none' -> chấp nhận paid để KHÔNG trả 503), vẫn band.
    'áp dụng với openai thôi' -> tier mặc định free_oai."""
    enabled: bool = True
    model: str = "openai/gpt-4o-mini"
    tier: str = "free_oai"                        # tier OpenAI để lấy key + provider
    band_tokens: int = 250_000


class LaneConfig(BaseModel):
    """1 làn của weighted_banded: 1 tier + trọng số RR + band xoay key riêng."""
    tier: str
    weight: int = 1
    band_tokens: int = 250_000


class BandedParams(BaseModel):
    """Params cho selector banded_rotation (default toàn hệ)."""
    band_tokens: int = 250_000
    save_mode: SaveModeConfig = Field(default_factory=SaveModeConfig)


class WeightedBandedParams(BaseModel):
    """Params cho selector weighted_banded (node think: blend gpt + deepseek)."""
    lanes: list[LaneConfig] = Field(default_factory=list)
    save_mode: SaveModeConfig = Field(default_factory=SaveModeConfig)


class SelectorConfig(BaseModel):
    impl: str = "banded_rotation"                 # ❖ DEFAULT toàn hệ (PLAN §5.8, §11.2)
    params: dict[str, Any] = Field(default_factory=dict)


class CapabilityConfig(BaseModel):
    """1 block/capability (PLAN §4b). tiers = thứ tự bậc thang cost."""
    tiers: list[str]                             # vd ["free_oai", "free_or", "paid"]
    # tier_name -> model_id ưu tiên. CÓ THỂ là 1 model (str) hoặc DANH SÁCH model
    # interchange (list): model đầu sập/biến mất -> tự thử model kế trong cùng tier.
    models: dict[str, str | list[str]] = Field(default_factory=dict)
    quality_floor: str | None = None             # model id tối thiểu (tùy chọn)
    require_tools: bool = False                   # answer/agent
    require_vision: bool = False                  # ocr/caption
    pinned_model: str | None = None              # embed -> pin (BẪY embedding, PLAN §4b)
    # ❖ MOSA hook: strategy RIÊNG cho node này (None -> dùng selector global).
    # vd think: weighted_banded (gpt-5.4-mini + deepseek-flash blend).
    selector: SelectorConfig | None = None

    def model_ids(self, tier: str) -> list[str]:
        """Danh sách model ưu tiên cho tier (interchange). str -> [str]; thiếu -> []."""
        v = self.models.get(tier)
        if v is None:
            return []
        return [v] if isinstance(v, str) else list(v)


class RoutingTable(BaseModel):
    version: int = 1
    selector: SelectorConfig = Field(default_factory=SelectorConfig)
    tiers: list[TierConfig] = Field(default_factory=list)
    capabilities: dict[str, CapabilityConfig] = Field(default_factory=dict)
    # ánh xạ alias gọi từ service -> capability (PLAN §4b). vd "auto"->"answer".
    aliases: dict[str, str] = Field(default_factory=dict)

    def resolve_capability(self, model_alias: str) -> str:
        if model_alias in self.capabilities:
            return model_alias
        return self.aliases.get(model_alias, model_alias)


def load_routing_table(path: str | os.PathLike[str]) -> RoutingTable:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"routing.yaml không tồn tại: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return RoutingTable.model_validate(data)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
