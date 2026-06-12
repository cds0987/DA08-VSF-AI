"""
Model-price catalog — nguồn giá để tự tính cost LLM gửi vào Langfuse generation.

Vì sao tự tính: Langfuse self-host = v2, bảng pricing nội bộ KHÔNG có model mới
(gpt-5.4-mini...). Nên ta lấy giá từ dataset OpenRouter (`gunnybd01/openrouter-models-cache`),
nhân với token usage, gửi thẳng input_cost/output_cost/total_cost vào generation.

BUNDLE-AT-BUILD: runtime CHỈ đọc `model_prices.json` (đã bundle vào image lúc build) ->
KHÔNG cần huggingface_hub/pyarrow ở runtime (image nhẹ, VM không cần outbound HF). Việc
tải parquet từ HF + parse -> JSON do builder stage làm lúc build image (CI có internet),
xem scripts/build_price_catalog.py. JSON seed commit kèm repo làm fallback khi build
không lấy được HF.

Mọi lỗi đều nuốt: catalog rỗng = cost bị bỏ qua, KHÔNG bao giờ làm vỡ boot/query.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float:
    """OpenRouter pricing là string ('0.00000075', '0'); None/parse lỗi -> 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_model(model: str | None) -> str:
    """
    Chuẩn hoá tên model để đối chiếu env <-> dataset.

    Dataset `id` = 'openai/gpt-5.4-mini'; env OPENAI_LLM_MODEL = 'gpt-5.4-mini'.
    Bỏ prefix 'provider/' + lowercase -> khớp trực tiếp. (Field `name`
    "OpenAI: GPT-5.4 Mini" parse không ổn định nên KHÔNG dùng.)
    """
    m = (model or "").strip().lower()
    if "/" in m:
        m = m.rsplit("/", 1)[-1]
    return m


class PriceCatalog:
    """Map normalized_model_id -> {prompt, completion, cache_read} (USD/token)."""

    def __init__(self, prices: dict[str, dict[str, float]]) -> None:
        self._prices = prices

    def __len__(self) -> int:
        return len(self._prices)

    def lookup(self, model: str | None) -> dict[str, float] | None:
        return self._prices.get(_normalize_model(model))

    def cost(
        self,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> dict[str, float] | None:
        """
        Trả {input_cost, output_cost, total_cost} (USD) hoặc None nếu không có giá.

        Token cache-read (đã có trong input_tokens) tính theo giá rẻ hơn nếu dataset
        có `input_cache_read`, phần còn lại theo `prompt`.
        """
        pricing = self.lookup(model)
        if not pricing:
            return None
        prompt = pricing.get("prompt", 0.0)
        completion = pricing.get("completion", 0.0)
        # Dataset dùng -1 làm sentinel "giá biến động/không áp" -> coi như không có giá.
        if prompt < 0 or completion < 0:
            return None
        cache_read = pricing.get("cache_read") or prompt
        non_cached = max(int(input_tokens) - int(cached_tokens), 0)
        input_cost = non_cached * prompt + int(cached_tokens) * cache_read
        output_cost = int(output_tokens) * completion
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": input_cost + output_cost,
        }


# ---------------------------------------------------------------------------
# Runtime: load JSON đã bundle (KHÔNG đụng HF/pyarrow).
# ---------------------------------------------------------------------------
def _read_json(path: str | None) -> dict[str, dict[str, float]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("price_catalog_json_read_failed", extra={"path": str(p), "error": str(exc)[:200]})
        return {}


def load_price_catalog(path: str, override_path: str | None = None) -> PriceCatalog:
    """
    Build catalog từ JSON đã bundle (`path`). `override_path` (tuỳ chọn, vd file trên
    volume) nếu tồn tại sẽ ĐÈ bản bundle -> cho phép cập nhật giá nóng không cần rebuild.

    Best-effort tuyệt đối: thiếu/lỗi file -> catalog rỗng (cost bị bỏ qua).
    """
    prices = _read_json(path)
    override = _read_json(override_path)
    if override:
        prices = {**prices, **override}
        logger.info("price_catalog_override_applied", extra={"models": len(override)})
    if prices:
        logger.info("price_catalog_loaded", extra={"models": len(prices)})
    else:
        logger.warning("price_catalog_empty", extra={"path": path})
    return PriceCatalog(prices)


# ---------------------------------------------------------------------------
# Build-time ONLY: fetch giá qua HF datasets-server REST (JSON) -> dict.
# CHỈ dùng stdlib urllib (KHÔNG pyarrow/huggingface-hub) -> image build nhẹ & nhanh.
# KHÔNG gọi ở runtime — chỉ scripts/build_price_catalog.py dùng. Lỗi -> raise (build
# script bắt + giữ seed json đã commit làm fallback).
# ---------------------------------------------------------------------------
_DATASETS_SERVER = "https://datasets-server.huggingface.co"
_ROWS_PAGE = 100  # giới hạn datasets-server /rows


def _http_get_json(url: str, timeout: float = 30.0) -> dict:
    import json as _json
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (URL nội bộ HF)
        return _json.loads(resp.read().decode("utf-8"))


def _first_config_split(repo_id: str) -> tuple[str, str]:
    from urllib.parse import quote

    data = _http_get_json(f"{_DATASETS_SERVER}/splits?dataset={quote(repo_id)}")
    splits = data.get("splits") or []
    if not splits:
        raise RuntimeError(f"datasets-server: no splits for {repo_id}")
    first = splits[0]
    return str(first["config"]), str(first["split"])


def fetch_prices_from_hf(repo_id: str, cache_dir: str | None = None) -> dict[str, dict[str, float]]:
    """Fetch giá model qua HF datasets-server /rows (JSON, phân trang). Raise nếu lỗi.

    Tên hàm giữ nguyên cho tương thích scripts/build_price_catalog.py. `cache_dir` không
    còn dùng (giữ chữ ký cũ)."""
    from urllib.parse import quote

    config, split = _first_config_split(repo_id)
    base = (
        f"{_DATASETS_SERVER}/rows?dataset={quote(repo_id)}"
        f"&config={quote(config)}&split={quote(split)}"
    )
    prices: dict[str, dict[str, float]] = {}
    offset = 0
    total = None
    while total is None or offset < total:
        page = _http_get_json(f"{base}&offset={offset}&length={_ROWS_PAGE}")
        total = page.get("num_rows_total", total or 0)
        rows = page.get("rows") or []
        if not rows:
            break
        for entry in rows:
            row = entry.get("row") or {}
            model_id = _normalize_model(row.get("id"))
            if not model_id:
                continue
            pricing = row.get("pricing") or {}
            prices[model_id] = {
                "prompt": _to_float(pricing.get("prompt")),
                "completion": _to_float(pricing.get("completion")),
                "cache_read": _to_float(pricing.get("input_cache_read")),
            }
        offset += len(rows)
    if not prices:
        raise RuntimeError("fetched price catalog is empty")
    return prices
