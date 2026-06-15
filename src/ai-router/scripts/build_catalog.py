#!/usr/bin/env python3
"""Build-time: tải toàn bộ model + pricing + window + capability từ OpenRouter /models
-> ghi config/model_catalog.json (bundle vào image). Chạy lúc deploy (public, KHÔNG cần key).

Catalog DÙNG CHUNG cho router (chọn model) + Langfuse (tính cost). PLAN §9 bước 1.

Dùng:
    python scripts/build_catalog.py [out_json] [--fee 0.055]

Best-effort: lỗi mạng -> giữ seed JSON đã commit (không ghi đè bằng rỗng), exit 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"
DEFAULT_OUT = "config/model_catalog.json"
SUPPLEMENT = "config/openai_supplement.json"  # model OpenAI-direct OpenRouter KHÔNG có (embeddings)
DEFAULT_FEE = 0.055  # phí pay-as-you-go OpenRouter; 0 nếu không cộng


def _fnum(pricing: dict, key: str) -> float:
    v = pricing.get(key)
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _split_provider(model_id: str) -> tuple[str, str]:
    """'openai/gpt-4o-mini' -> ('openai', 'gpt-4o-mini'). Không có '/' -> provider rỗng."""
    if "/" in model_id:
        prov, native = model_id.split("/", 1)
        return prov.lower(), native
    return "", model_id


def _endpoint_for(model_id: str, modalities: list[str]) -> str:
    mid = model_id.lower()
    if "embedding" in mid or "embed" in mid:
        return "embeddings"
    # codex/responses-only — không gọi được /chat/completions (PLAN §6)
    if "codex" in mid:
        return "responses"
    return "chat"


def transform(m: dict, fee: float) -> dict:
    arch = m.get("architecture") or {}
    top = m.get("top_provider") or {}
    pricing = m.get("pricing") or {}
    model_id = m.get("id", "")
    provider, native = _split_provider(model_id)

    p_in = _fnum(pricing, "prompt") * 1_000_000      # USD/token -> USD/Mtok
    p_out = _fnum(pricing, "completion") * 1_000_000
    is_free = _fnum(pricing, "prompt") == 0.0 and _fnum(pricing, "completion") == 0.0
    supported = m.get("supported_parameters") or []
    modalities = arch.get("input_modalities") or ["text"]

    return {
        "id": model_id,
        "provider": provider,
        "name_native": native,
        "name_or": model_id,
        "context_length": int(m.get("context_length") or top.get("context_length") or 0),
        "price_in_per_mtok": round(p_in, 6),
        "price_out_per_mtok": round(p_out, 6),
        "price_in_with_fee": round(p_in * (1 + fee), 6),
        "price_out_with_fee": round(p_out * (1 + fee), 6),
        "is_free": is_free,
        "supports_tools": ("tools" in supported or "tool_choice" in supported),
        "input_modalities": modalities,
        "endpoint": _endpoint_for(model_id, modalities),
    }


def fetch(fee: float) -> list[dict]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(MODELS_ENDPOINT)
        r.raise_for_status()
        data = r.json().get("data", [])
    out = [transform(m, fee) for m in data if m.get("id")]
    if not out:
        raise RuntimeError("catalog rỗng từ OpenRouter")
    return out


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") else Path(DEFAULT_OUT)
    fee = DEFAULT_FEE
    if "--fee" in argv:
        fee = float(argv[argv.index("--fee") + 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        models = fetch(fee)
        # merge supplement (OpenAI-direct: embeddings...) — supplement override theo id
        sup_path = out_path.parent / "openai_supplement.json"
        if sup_path.exists():
            sup = json.loads(sup_path.read_text(encoding="utf-8"))
            by_id = {m["id"]: m for m in models}
            for s in sup:
                by_id[s["id"]] = s
            models = list(by_id.values())
        out_path.write_text(json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")
        free = sum(1 for x in models if x["is_free"])
        print(f"catalog OK: {len(models)} model ({free} free) -> {out_path}")
    except Exception as exc:  # noqa: BLE001 — không chặn deploy vì hụt mạng
        if out_path.exists():
            print(f"WARN fetch lỗi ({str(exc)[:160]}); giữ seed {out_path}")
        else:
            out_path.write_text("[]", encoding="utf-8")
            print(f"WARN fetch lỗi ({str(exc)[:160]}); KHÔNG có seed -> ghi rỗng {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
