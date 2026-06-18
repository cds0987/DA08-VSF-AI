"""Catalog model — nạp model_catalog.json (build từ OpenRouter /models).

Dùng cho: router (chọn model theo window/tools/vision/giá) + Langfuse (giá -> cost).
Best-effort: thiếu/lỗi file -> catalog rỗng, KHÔNG vỡ boot.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .schemas import ModelEntry, Provider

logger = logging.getLogger("ai_router.catalog")

# Đuôi snapshot ngày provider hay gắn: "-2026-03-17" hoặc "-20260423". Strip để GOM model
# (gpt-5.4-mini-2026-03-17 -> gpt-5.4-mini). KHÔNG fuzzy (quyết định: chỉ strip date).
_DATE_RE = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8})$")


class Catalog:
    def __init__(self, models: list[ModelEntry]) -> None:
        self._by_id: dict[str, ModelEntry] = {m.id: m for m in models}
        # tra cứu theo tên trần (OpenAI direct) — vd "gpt-4o-mini"
        self._by_native: dict[str, ModelEntry] = {m.name_native: m for m in models}

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, model_id: str) -> ModelEntry | None:
        return self._by_id.get(model_id) or self._by_native.get(model_id)

    def canonicalize(self, raw_id: str) -> tuple[str, str]:
        """Chuẩn hoá model id provider trả về -> id CANONICAL trong catalog.

        Trả (canonical_id, kind) với kind ∈ {exact, date_strip, unmatched}:
          - exact      : khớp thẳng catalog (by_id hoặc by_native).
          - date_strip : bỏ đuôi ngày rồi mới khớp (gpt-5.4-mini-2026-03-17 -> openai/gpt-5.4-mini).
          - unmatched  : không có trong catalog -> trả bản đã strip date (cờ drift cho caller).
        KHÔNG fuzzy (tránh đoán sai giá). Caller phát metric khi 'unmatched'.
        """
        hit = self._by_id.get(raw_id) or self._by_native.get(raw_id)
        if hit:
            return hit.id, "exact"
        stripped = _DATE_RE.sub("", raw_id)
        if stripped != raw_id:
            hit = self._by_id.get(stripped) or self._by_native.get(stripped)
            if hit:
                return hit.id, "date_strip"
        return stripped, "unmatched"

    def all(self) -> list[ModelEntry]:
        return list(self._by_id.values())

    def candidates(
        self,
        *,
        provider: Provider,
        is_free: bool | None = None,
        require_tools: bool = False,
        require_vision: bool = False,
        min_context: int = 0,
        endpoint: str | None = None,
    ) -> list[ModelEntry]:
        """Lọc model KHẢ THI cho 1 (provider, ràng buộc) — PLAN §5.4."""
        out: list[ModelEntry] = []
        for m in self._by_id.values():
            if provider == Provider.OPENAI and m.provider != "openai":
                continue  # OpenAI key chỉ gọi được model openai (provider-split)
            if is_free is not None and m.is_free != is_free:
                continue
            if require_tools and not m.supports_tools:
                continue
            if require_vision and not m.is_vision():
                continue
            if min_context and m.context_length and m.context_length < min_context:
                continue
            if endpoint and m.endpoint != endpoint:
                continue
            out.append(m)
        return out

    def cost(self, model_id: str, in_tok: int, out_tok: int, with_fee: bool = True) -> float | None:
        """USD ước tính cho 1 call (dùng khi provider không trả cost, vd OpenAI). PLAN §5.7.

        Chịu được id có đuôi ngày: get() trượt -> thử bản canonical (strip-date) trước khi bỏ cuộc
        -> bản dated KHÔNG còn về cost $0."""
        m = self.get(model_id)
        if not m:
            canon, kind = self.canonicalize(model_id)
            if kind != "unmatched":
                m = self.get(canon)
        if not m:
            return None
        pin = m.price_in_with_fee if with_fee else m.price_in_per_mtok
        pout = m.price_out_with_fee if with_fee else m.price_out_per_mtok
        return (in_tok * pin + out_tok * pout) / 1_000_000


def load_catalog(path: str | Path) -> Catalog:
    p = Path(path)
    if not p.exists():
        logger.warning("catalog_missing path=%s -> rỗng", p)
        return Catalog([])
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        models = [ModelEntry.model_validate(x) for x in raw]
        logger.info("catalog_loaded models=%d path=%s", len(models), p)
        return Catalog(models)
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog_load_failed path=%s err=%s", p, str(exc)[:200])
        return Catalog([])
