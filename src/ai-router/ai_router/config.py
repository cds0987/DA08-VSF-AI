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


class TierConfig(BaseModel):
    name: str                                    # "free_oai" | "free_or" | "paid"
    endpoint_default: str = "chat"


class CapabilityConfig(BaseModel):
    """1 block/capability (PLAN §4b). tiers = thứ tự bậc thang cost."""
    tiers: list[str]                             # vd ["free_oai", "free_or", "paid"]
    models: dict[str, str] = Field(default_factory=dict)  # tier_name -> model_id ưu tiên
    quality_floor: str | None = None             # model id tối thiểu (tùy chọn)
    require_tools: bool = False                   # answer/agent
    require_vision: bool = False                  # ocr/caption
    pinned_model: str | None = None              # embed -> pin (BẪY embedding, PLAN §4b)


class SelectorConfig(BaseModel):
    impl: str = "sticky_rotation_soft"           # ❖ đổi thuật toán ở đây (PLAN §5.8)
    params: dict[str, Any] = Field(default_factory=dict)


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
