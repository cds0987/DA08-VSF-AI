from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAG_WORKER_SRC = ROOT / "src" / "rag-worker"
if str(RAG_WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_WORKER_SRC))

from core_engine.config_loader import resolve_config_dict
from core_engine.config_schema import PipelineConfig
from core_engine.mapping import build_ai_settings, to_vector_store_config

# Contract chỉ phụ thuộc embedder + vector_store (+ ai_mode). Validate SUBSET để
# script chạy được trên CẢ config rag-worker (ingest-only) lẫn mcp-service
# (search-only: có reranker/retrieval mà PipelineConfig ingest-only forbid).
_CONTRACT_KEYS = ("common", "embedder", "vector_store", "vectorstore_contract")


def _load_contract(path: Path) -> tuple[str, str, str]:
    resolved = resolve_config_dict(path)
    subset = {key: resolved[key] for key in _CONTRACT_KEYS if key in resolved}
    cfg = PipelineConfig.model_validate(subset)
    ai_settings = build_ai_settings(cfg)
    vector_config = to_vector_store_config(cfg, dim=ai_settings.embed_dimension or 0)
    contract = vector_config.contract()
    return contract.index_id, contract.fingerprint, (
        f"provider={contract.provider} collection={contract.collection} "
        f"model={contract.embed_model} dim={contract.dimension} schema={contract.schema_version}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check vectorstore contract parity across configs.")
    parser.add_argument(
        "left",
        nargs="?",
        default=str(ROOT / "src" / "rag-worker" / "config.yaml"),
    )
    parser.add_argument(
        "right",
        nargs="?",
        default=str(ROOT / "src" / "mcp-service" / "config.yaml"),
    )
    args = parser.parse_args()

    left_path = Path(args.left).resolve()
    right_path = Path(args.right).resolve()
    missing = [str(path) for path in (left_path, right_path) if not path.is_file()]
    if missing:
        print("Missing config file(s):")
        for item in missing:
            print(f"  - {item}")
        return 2

    left_index, left_fp, left_summary = _load_contract(left_path)
    right_index, right_fp, right_summary = _load_contract(right_path)
    if left_fp != right_fp or left_index != right_index:
        print("Vectorstore contract mismatch:")
        print(f"  left : {left_path}")
        print(f"         {left_summary}")
        print(f"         index={left_index} fp={left_fp}")
        print(f"  right: {right_path}")
        print(f"         {right_summary}")
        print(f"         index={right_index} fp={right_fp}")
        return 1

    print(f"Vectorstore contract OK: index={left_index} fp={left_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
