#!/usr/bin/env python3
"""GATE MCP result: khoá shape kết quả tool MCP giữa mcp-service (producer) và query-service
(consumer) — infra/mcp/tool-result-contract.yaml. Bắt drift ÂM THẦM: query parse RẤT khoan dung
(any-of) nên mcp đổi field KHÔNG crash, chỉ degrade (mất nguồn/citation). Thuần tĩnh (AST). Lệch=1.

  (a) producer `_hit_to_dict` emit ⊇ canonical_fields (mcp bỏ/đổi field canonical -> đỏ).
  (b) consumer `_search_result_from_payload` tham chiếu MỖI canonical field (.get("X")).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "infra" / "mcp" / "tool-result-contract.yaml"


def _parse(rel: str) -> ast.AST | None:
    p = ROOT / rel
    return ast.parse(p.read_text(encoding="utf-8")) if p.exists() else None


def _fn(tree: ast.AST, name: str) -> ast.AST | None:
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _dict_keys(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _get_calls(node: ast.AST) -> set[str]:
    """Mọi obj.get("X") string arg trong node (consumer đọc field)."""
    reads: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                reads.add(a.value)
    return reads


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML chưa cài"); return 2
    c = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    errors: list[str] = []

    for name, spec in c.items():
        if name == "version" or not isinstance(spec, dict):
            continue
        canonical = set(spec["canonical_fields"])

        ptree = _parse(spec["producer"]["file"])
        pnode = _fn(ptree, spec["producer"]["marker"]) if ptree else None
        if pnode is None:
            errors.append(f"[{name}] KHÔNG thấy producer {spec['producer']['marker']!r} "
                          f"trong {spec['producer']['file']}")
        else:
            pkeys = _dict_keys(pnode)
            missing = canonical - pkeys
            if missing:
                errors.append(f"[{name}] producer ({spec['producer']['marker']}) KHÔNG emit "
                              f"canonical field {sorted(missing)} -> consumer mất dữ liệu (degrade). "
                              f"Nếu CHỦ ĐÍCH đổi shape, cập nhật canonical_fields.")

        ctree = _parse(spec["consumer"]["file"])
        cnode = _fn(ctree, spec["consumer"]["marker"]) if ctree else None
        if cnode is None:
            errors.append(f"[{name}] KHÔNG thấy consumer {spec['consumer']['marker']!r} "
                          f"trong {spec['consumer']['file']}")
        else:
            reads = _get_calls(cnode)
            not_read = canonical - reads
            if not_read:
                errors.append(f"[{name}] consumer ({spec['consumer']['marker']}) KHÔNG còn đọc "
                              f"canonical field {sorted(not_read)} -> bỏ sót dữ liệu mcp gửi.")

    if errors:
        print("MCP RESULT LINT - FAIL:")
        for e in errors:
            print("  x", e)
        return 1
    print("MCP RESULT LINT OK: producer emit ⊇ canonical, consumer đọc đủ canonical field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
