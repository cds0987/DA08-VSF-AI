#!/usr/bin/env python3
"""validate_manifest — CI gác MOSA cho monitor_decision.

Manifest (config.yaml) là NGUỒN SỰ THẬT. Script này đối soát để "lệch là CI đỏ":
  1. module descriptor đủ field + file contract tồn tại.
  2. monitor.dashboards: mỗi entry -> file tồn tại; id duy nhất.
  3. KHÔNG mồ côi: mọi *.json trong thư mục provision phải có entry.
  4. metric-contract: mọi metric (theo namespace prefix) panel query PHẢI khai trong contract.
  5. tree.observe ref type=grafana -> phải khớp 1 dashboard id.
  6. decision: strategy_source (trỏ routing.yaml) + control_plane tồn tại.

Chạy: python deploy/monitor_decision/scripts/validate_manifest.py
Phụ thuộc: pyyaml (CI cài). Stdlib còn lại.
"""
from __future__ import annotations

import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # deploy/monitor_decision
DASH_DIR = os.path.join(ROOT, "monitor", "grafana", "dashboards")
METRIC_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _exists(rel: str) -> bool:
    return os.path.isfile(os.path.join(ROOT, rel))


def _walk_expr(node) -> list[str]:
    """Gom mọi value dưới key 'expr' (đệ quy, kể cả panel lồng trong row)."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "expr" and isinstance(v, str):
                out.append(v)
            else:
                out += _walk_expr(v)
    elif isinstance(node, list):
        for it in node:
            out += _walk_expr(it)
    return out


def main() -> int:
    cfg = _load_yaml(os.path.join(ROOT, "config.yaml"))

    # 1. module descriptor ----------------------------------------------------
    module = cfg.get("module") or {}
    for key in ("id", "title", "version", "manifest", "provides", "contracts"):
        if key not in module:
            err(f"module: thiếu field bắt buộc '{key}'")
    for c in module.get("contracts", []):
        if not _exists(c):
            err(f"module.contracts: file '{c}' không tồn tại")

    # 2 + 3. dashboards <-> file ----------------------------------------------
    dash = (cfg.get("monitor") or {}).get("dashboards") or []
    ids: set[str] = set()
    declared_files: set[str] = set()
    for d in dash:
        did, dfile = d.get("id"), d.get("file")
        if did in ids:
            err(f"monitor.dashboards: id trùng '{did}'")
        ids.add(did)
        if not dfile or not _exists(dfile):
            err(f"monitor.dashboards[{did}]: file '{dfile}' không tồn tại")
        else:
            declared_files.add(os.path.normpath(os.path.join(ROOT, dfile)))

    if os.path.isdir(DASH_DIR):
        for fn in os.listdir(DASH_DIR):
            if fn.endswith(".json"):
                ap = os.path.normpath(os.path.join(DASH_DIR, fn))
                if ap not in declared_files:
                    err(f"dashboard MỒ CÔI: '{fn}' có trong thư mục provision nhưng KHÔNG khai ở config.yaml")

    # 4. metric-contract <-> expr --------------------------------------------
    mc = _load_yaml(os.path.join(ROOT, "monitor", "metric-contract.yaml"))
    namespaces = (mc.get("namespaces") or {})
    declared_metrics: set[str] = set()
    for body in namespaces.values():
        for m in (body or {}).get("metrics", []):
            declared_metrics.add(m["name"])
    managed_prefixes = tuple(f"{ns}_" for ns in namespaces)  # airouter_, vsf_, node_, qdrant_

    for did in ids:
        entry = next((d for d in dash if d.get("id") == did), None)
        if not entry or not _exists(entry["file"]):
            continue
        with open(os.path.join(ROOT, entry["file"]), encoding="utf-8") as f:
            board = json.load(f)
        for expr in _walk_expr(board):
            for tok in METRIC_RE.findall(expr):
                if tok.startswith(managed_prefixes) and tok not in declared_metrics:
                    err(f"dashboard[{did}]: metric '{tok}' query nhưng CHƯA khai trong metric-contract.yaml")

    # 5. tree.observe grafana ref -> dashboard id -----------------------------
    for node in cfg.get("tree", []):
        for o in node.get("observe", []) or []:
            if o.get("type") == "grafana" and o.get("ref") not in ids:
                err(f"tree[{node.get('id')}].observe: grafana ref '{o.get('ref')}' không khớp dashboard id nào")

    # 6. decision -------------------------------------------------------------
    dec = cfg.get("decision") or {}
    for key in ("strategy_source", "control_plane"):
        rel = dec.get(key)
        if not rel or not _exists(rel):
            err(f"decision.{key}: '{rel}' không tồn tại")

    # ------------------------------------------------------------------------
    if errors:
        print("[FAIL] MANIFEST KHONG HOP LE:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[OK] manifest OK: {len(ids)} dashboard, {len(declared_metrics)} metric khai, "
          f"{len(namespaces)} namespace. Khong lech.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
