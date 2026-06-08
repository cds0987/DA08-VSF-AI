"""Contract-parity guard PHÍA mcp-service (consumer) vs rag-worker (producer).

Khác bản cũ ở rag-worker: mcp-service nest embedder/vector_store/vectorstore_contract
DƯỚI section tool `rag_search` (mọi config tool-local nest vào tool). Loader của
rag-worker CẤM `embedder` nằm ngoài top-level nên KHÔNG đọc được config mcp. Vì vậy
parity được tính bất đối xứng, mỗi bên bằng loader CỦA CHÍNH NÓ:

- rag-worker contract: dùng core_engine.config_loader (config rag-worker top-level,
  guard pass) — KHÔNG sửa gì rag-worker, chỉ import đọc.
- mcp-service contract: dùng app.core.config.load_settings() (hiểu layout nest).

So index_id + fingerprint. Lệch -> exit 1 (chặn build như guard cũ).

sys.path đặt mcp-service TRƯỚC rag-worker: `import app...` -> app của mcp; rag-worker
chỉ được import qua `core_engine.*` (tên rời, không đụng `app`) nên không xung đột.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MCP_SRC = ROOT / "src" / "mcp-service"
RAG_WORKER_SRC = ROOT / "src" / "rag-worker"
for entry in (str(RAG_WORKER_SRC), str(MCP_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)  # MCP_SRC chèn sau -> đứng trước -> `app` = mcp


def _rag_worker_contract(path: Path) -> tuple[str, str, str]:
    from core_engine.config_loader import resolve_config_dict
    from core_engine.config_schema import PipelineConfig
    from core_engine.mapping import build_ai_settings, to_vector_store_config

    # Contract chỉ phụ thuộc common/embedder/vector_store/vectorstore_contract.
    keys = ("common", "embedder", "vector_store", "vectorstore_contract")
    resolved = resolve_config_dict(path)
    subset = {key: resolved[key] for key in keys if key in resolved}
    cfg = PipelineConfig.model_validate(subset)
    ai_settings = build_ai_settings(cfg)
    contract = to_vector_store_config(cfg, dim=ai_settings.embed_dimension or 0).contract()
    return contract.index_id, contract.fingerprint, (
        f"provider={contract.provider} collection={contract.collection} "
        f"model={contract.embed_model} dim={contract.dimension}"
    )


def _mcp_service_contract(path: Path) -> tuple[str, str, str]:
    from app.core.config import load_settings

    contract = load_settings(path).contract()
    return contract.index_id, contract.fingerprint, (
        f"provider={contract.provider} collection={contract.collection} "
        f"model={contract.embed_model} dim={contract.dimension}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check vectorstore contract parity rag-worker (producer) vs mcp-service (consumer)."
    )
    parser.add_argument("rag_worker_config", nargs="?", default=str(RAG_WORKER_SRC / "config.yaml"))
    parser.add_argument("mcp_service_config", nargs="?", default=str(MCP_SRC / "config.yaml"))
    args = parser.parse_args()

    left_path = Path(args.rag_worker_config).resolve()
    right_path = Path(args.mcp_service_config).resolve()
    missing = [str(p) for p in (left_path, right_path) if not p.is_file()]
    if missing:
        print("Missing config file(s):")
        for item in missing:
            print(f"  - {item}")
        return 2

    left_index, left_fp, left_summary = _rag_worker_contract(left_path)
    right_index, right_fp, right_summary = _mcp_service_contract(right_path)
    if left_fp != right_fp or left_index != right_index:
        print("Vectorstore contract mismatch:")
        print(f"  rag-worker : {left_path}")
        print(f"               {left_summary}")
        print(f"               index={left_index} fp={left_fp}")
        print(f"  mcp-service: {right_path}")
        print(f"               {right_summary}")
        print(f"               index={right_index} fp={right_fp}")
        return 1

    print(f"Vectorstore contract OK: index={left_index} fp={left_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
