#!/usr/bin/env python3
"""
Build-time: tải giá model từ dataset OpenRouter trên HF -> ghi model_prices.json để
BUNDLE vào image. Chạy ở builder stage (CI có internet); runtime KHÔNG chạy cái này.

Fallback: nếu HF lỗi (offline/down lúc build) -> giữ nguyên file seed đã commit ở OUT
(không ghi đè bằng rỗng) để image không bao giờ tệ hơn bản seed. Luôn exit 0 để 1 cú
hụt mạng KHÔNG chặn deploy.

Dùng:
    python scripts/build_price_catalog.py <out_json_path> [repo_id]

Có thể chạy local để refresh file seed commit kèm repo:
    python scripts/build_price_catalog.py \
        app/infrastructure/observability/data/model_prices.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Cho phép `import app...` khi chạy từ thư mục query-service.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infrastructure.observability.price_catalog import (  # noqa: E402
    OPENAI_PRICE_SUPPLEMENT,
    fetch_prices_from_hf,
    fetch_prices_from_openrouter,
)

DEFAULT_REPO = "gunnybd01/openrouter-models-cache"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: build_price_catalog.py <out_json_path> [repo_id]", file=sys.stderr)
        return 2
    out_path = Path(sys.argv[1])
    repo_id = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MODEL_PRICE_DATASET_REPO", DEFAULT_REPO)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Nguồn ưu tiên: OpenRouter LIVE (model mới nhất). Hụt mạng -> HF dataset cache ->
    # seed đã commit. Luôn merge supplement embeddings. Luôn exit 0 (không chặn deploy).
    prices: dict | None = None
    try:
        prices = fetch_prices_from_openrouter()
        print(f"price catalog OK (OpenRouter live): {len(prices)} models")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN OpenRouter live failed ({str(exc)[:160]}); thử HF dataset…")
        try:
            prices = fetch_prices_from_hf(repo_id, cache_dir=None)
            prices.update(OPENAI_PRICE_SUPPLEMENT)
            print(f"price catalog OK (HF fallback): {len(prices)} models")
        except Exception as exc2:  # noqa: BLE001
            print(f"WARN HF fetch failed ({str(exc2)[:160]})")

    if prices:
        out_path.write_text(json.dumps(prices, separators=(",", ":")), encoding="utf-8")
        print(f"-> {out_path}")
    elif out_path.exists():
        print(f"giữ seed sẵn có tại {out_path}")
    else:
        out_path.write_text("{}", encoding="utf-8")
        print(f"KHÔNG có seed -> ghi rỗng {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
