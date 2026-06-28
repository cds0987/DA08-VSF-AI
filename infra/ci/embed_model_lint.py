#!/usr/bin/env python3
"""GATE EMBED-MODEL: ép registry embed model NHẤT QUÁN xuyên service (rag-worker ↔ ai-router).

Bắt class drift IM LẶNG vốn KHÔNG compile-error, KHÔNG test đơn nào đỏ — đã từng giết prod:
  - BUG qwen8b (2026-06-28): routing.yaml khai capability embed_e5large/bgem3/... nhưng
    router.embeddings() hardcode resolve('embed') -> MỌI model bị ép qwen8b -> multi-collection
    GIẢ (mọi collection lưu qwen8b cắt chiều). Im lặng tuyệt đối, chỉ lộ qua forensic cosine.
  - Gỡ/thêm 1 model phải sửa 4 file (embeddings.yaml + contract.py + routing.yaml + catalog);
    quên 1 chỗ = vỡ ngầm (model active không route được -> 503 / rơi về model khác).

NGUỒN SỰ THẬT (mỗi fact đúng 1 nơi; nơi khác PHẢI khớp, lint chốt):
  embeddings.yaml.embed_models        = MODEL ACTIVE (tập phải phủ ở mọi nơi dưới).
  contract.py EMBED_MODELS/MODEL_TAGS = dim native + collection-tag (rag-worker).
  routing.yaml aliases/capabilities   = model -> capability -> pinned_model + tier (ai-router).
  model_catalog.json                  = model selector pick được (ai-router).

Thuần tĩnh: parse YAML/JSON + AST contract.py. KHÔNG import service, KHÔNG cần hạ tầng
(chạy như nats_contract_lint / migration_lint). Lệch = exit 1 -> chặn build+deploy.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

try:  # console Windows (cp1252) không in được tiếng Việt; CI Linux đã utf-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[2]
EMBEDDINGS_YAML = ROOT / "src" / "rag-worker" / "embeddings.yaml"
CONTRACT_PY = ROOT / "src" / "rag-worker" / "core_engine" / "contract.py"
ROUTING_YAML = ROOT / "src" / "ai-router" / "routing.yaml"
CATALOG_JSON = ROOT / "src" / "ai-router" / "config" / "model_catalog.json"


def _dict_keys_from_assign(src: str, name: str) -> set[str]:
    """AST: string-keys của dict gán cho biến `name` (vd EMBED_MODELS) trong contract.py.
    Tĩnh — KHÔNG import (contract.py thuần stdlib nhưng giữ pattern static như nats lint)."""
    for node in _dict_assigns(ast.parse(src)):
        names, value = node
        if name in names and isinstance(value, ast.Dict):
            return {
                k.value for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    return set()


def _dict_assigns(tree: ast.AST):
    """Yield (target_names, value) cho cả Assign (X = {..}) LẪN AnnAssign (X: T = {..}).
    EMBED_MODELS có type-annotation -> là AnnAssign (KHÔNG .targets); MODEL_TAGS là Assign."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            yield ({t.id for t in node.targets if isinstance(t, ast.Name)}, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield ({node.target.id}, node.value)


def _catalog_ids(raw) -> set[str]:
    models = raw if isinstance(raw, list) else raw.get("models", [])
    return {m.get("id") for m in models if isinstance(m, dict) and m.get("id")}


def main() -> int:
    import yaml  # CI job cài pyyaml (như nats_contract_lint / manifest-lint)

    errors: list[str] = []
    for p in (EMBEDDINGS_YAML, CONTRACT_PY, ROUTING_YAML, CATALOG_JSON):
        if not p.exists():
            print(f"embed-model-lint: THIẾU file {p}", file=sys.stderr)
            return 1

    active = yaml.safe_load(EMBEDDINGS_YAML.read_text(encoding="utf-8")).get("embed_models") or []
    csrc = CONTRACT_PY.read_text(encoding="utf-8")
    embed_models = _dict_keys_from_assign(csrc, "EMBED_MODELS")
    model_tags = _dict_keys_from_assign(csrc, "MODEL_TAGS")
    routing = yaml.safe_load(ROUTING_YAML.read_text(encoding="utf-8"))
    aliases = routing.get("aliases", {}) or {}
    caps = routing.get("capabilities", {}) or {}
    catalog_ids = _catalog_ids(json.loads(CATALOG_JSON.read_text(encoding="utf-8")))

    if not active:
        errors.append("embeddings.yaml: embed_models RỖNG (ít nhất phải có primary qwen8b)")

    # MỖI model active PHẢI nhất quán ở MỌI nơi (đây là cái bắt drift kiểu qwen8b).
    for m in active:
        # 1) rag-worker contract: dim + collection-tag
        if m not in embed_models:
            errors.append(f"{m}: THIẾU trong contract.EMBED_MODELS (không có native dim)")
        if m not in model_tags:
            errors.append(f"{m}: THIẾU trong contract.MODEL_TAGS (collection-tag -> nguy cơ tag trùng)")
        # 2) ai-router routing: alias -> capability -> pinned_model + tier
        cap = aliases.get(m)
        if cap is None:
            errors.append(
                f"{m}: THIẾU alias trong ai-router routing.yaml -> router KHÔNG route được "
                f"(rơi về 503 / model khác — đúng class bug qwen8b)")
        else:
            capcfg = caps.get(cap)
            if capcfg is None:
                errors.append(f"{m}: alias -> '{cap}' nhưng capability '{cap}' KHÔNG tồn tại trong routing.yaml")
            else:
                pinned = capcfg.get("pinned_model")
                if pinned != m:
                    errors.append(f"{m}: capability '{cap}' pinned_model={pinned!r} (PHẢI = {m!r})")
                if not capcfg.get("tiers"):
                    errors.append(f"{m}: capability '{cap}' THIẾU tiers (không biết provider/key)")
        # 3) ai-router catalog: selector pick được model
        if m not in catalog_ids:
            errors.append(f"{m}: THIẾU trong model_catalog.json -> selector không pick được model")

    # Collection-tag PHẢI distinct giữa các model active (tag trùng = ghi đè collection).
    tags_active = [t for m in active if (t := _tag_of(csrc, m)) is not None]
    dup = {t for t in tags_active if tags_active.count(t) > 1}
    if dup:
        errors.append(f"collection-tag TRÙNG giữa model active {sorted(dup)} -> 2 model ghi chung 1 collection")

    if errors:
        print("✗ EMBED-MODEL DRIFT (chặn deploy):")
        for e in errors:
            print(f"    ✗ {e}")
        print(f"\n{len(errors)} lệch. Sửa cho khớp NGUỒN SỰ THẬT rồi push lại.")
        return 1
    print(f"✓ embed-model-lint OK: {len(active)} model active nhất quán xuyên service "
          f"(contract + routing.yaml + catalog).")
    return 0


def _tag_of(contract_src: str, model: str) -> str | None:
    """Đọc tag của model từ MODEL_TAGS literal (AST) — để check distinct mà không import."""
    tree = ast.parse(contract_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "MODEL_TAGS":
                    for k, v in zip(node.value.keys, node.value.values):
                        if (isinstance(k, ast.Constant) and k.value == model
                                and isinstance(v, ast.Constant)):
                            return v.value
    return None


if __name__ == "__main__":
    sys.exit(main())
