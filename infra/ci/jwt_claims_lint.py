#!/usr/bin/env python3
"""GATE JWT: ép producer (user-service) ↔ consumer (query/document/hr) khớp hợp đồng claims
(infra/auth/jwt-claims-contract.yaml). Bắt drift ÂM THẦM nguy hiểm cho ACL.

Thuần tĩnh (AST), không hạ tầng/không import service -> chạy như migration_lint. Lệch = exit 1.

Gate:
  A. PRODUCER phát ĐÚNG issued_claims (snapshot khoá) — đổi/bỏ/rename claim = đỏ -> buộc
     review consumer (chống rename account_type gây fail-open).
  B. Consumer 'required' (đọc payload["X"] cứng) ⊆ issued ∪ compat_aliases — chống consumer
     phụ thuộc claim producer không phát (401 fail-closed mọi token).
  C. Consumer đọc claim ACL-critical mà producer KHÔNG phát -> PHẢI khai known_unissued_acl_reads
     (chống thêm GAP fail-open mới như account_type bị rename; GAP department đã ghi nhận).
  D. secret_env (JWT_SECRET_KEY) hiện diện trong config MỌI service — chống lệch tên biến (401 lúc deploy).
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
CONTRACT = ROOT / "infra" / "auth" / "jwt-claims-contract.yaml"
_PAYLOAD_NAMES = {"payload", "claims", "p", "decoded", "token_data"}


def _parse(rel: str) -> ast.AST | None:
    p = ROOT / rel
    return ast.parse(p.read_text(encoding="utf-8")) if p.exists() else None


def _fn_node(tree: ast.AST, name: str) -> ast.AST | None:
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _producer_claims(node: ast.AST) -> set[str]:
    """String key của mọi dict literal trong encoder (payload truyền vào jwt.encode)."""
    keys: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _consumer_reads(node: ast.AST) -> tuple[set[str], set[str]]:
    """(required, soft): required = payload["X"] subscript; soft = payload.get("X"[, d])."""
    required: set[str] = set()
    soft: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in _PAYLOAD_NAMES:
            s = n.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                required.add(s.value)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            v = n.func.value
            if isinstance(v, ast.Name) and v.id in _PAYLOAD_NAMES and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    soft.add(a.value)
    return required, soft


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML chưa cài"); return 2
    c = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    issued = set(c["issued_claims"])
    aliases = set(c.get("compat_aliases") or [])
    acl = set(c.get("acl_critical") or [])
    known = {k: set(v) for k, v in (c.get("known_unissued_acl_reads") or {}).items()}
    errors: list[str] = []

    # A. PRODUCER phát đúng issued
    ptree = _parse(c["producer"]["encoder_file"])
    if ptree is None:
        errors.append(f"producer encoder_file không tồn tại: {c['producer']['encoder_file']}")
    else:
        pnode = _fn_node(ptree, c["producer"]["encoder_marker"])
        if pnode is None:
            errors.append(f"KHÔNG thấy encoder {c['producer']['encoder_marker']!r} (ref cũ?)")
        else:
            got = _producer_claims(pnode)
            if got != issued:
                errors.append(f"PRODUCER claims LỆCH snapshot: dư {sorted(got - issued)} | "
                              f"thiếu {sorted(issued - got)} -> cập nhật issued_claims + review consumer.")

    # B + C. mỗi consumer
    for svc, spec in (c.get("consumers") or {}).items():
        ctree = _parse(spec["decoder_file"])
        if ctree is None:
            errors.append(f"[{svc}] decoder_file không tồn tại: {spec['decoder_file']}"); continue
        cnode = _fn_node(ctree, spec["decoder_marker"])
        if cnode is None:
            errors.append(f"[{svc}] KHÔNG thấy decoder {spec['decoder_marker']!r} (ref cũ?)"); continue
        required, soft = _consumer_reads(cnode)
        # B: required cứng ⊆ issued ∪ aliases
        bad_req = required - issued - aliases
        if bad_req:
            errors.append(f"[{svc}] consumer REQUIRE (payload[...]) claim không được phát "
                          f"{sorted(bad_req)} -> 401 mọi token. Thêm vào issued hoặc đừng require.")
        # C: đọc claim ACL không-được-phát -> phải khai known_unissued_acl_reads
        acl_unissued = (required | soft) & acl - issued
        undocumented = acl_unissued - known.get(svc, set())
        if undocumented:
            errors.append(f"[{svc}] đọc claim ACL-critical KHÔNG được phát {sorted(undocumented)} "
                          f"-> rơi default = phân quyền sai (fail-open). Nếu CHỦ ĐÍCH, khai vào "
                          f"known_unissued_acl_reads[{svc}]; tốt hơn: sửa producer phát claim đó.")

    # D. secret_env hiện diện trong config mọi service
    secret = c["secret_env"]
    for svc, spec in (c.get("consumers") or {}).items():
        cfg = ROOT / "src" / svc / "app" / "infrastructure" / "config.py"
        if not cfg.exists():
            cfg = ROOT / "src" / svc / "app" / "core" / "config.py"
        if cfg.exists() and secret not in cfg.read_text(encoding="utf-8"):
            errors.append(f"[{svc}] config KHÔNG tham chiếu {secret} -> nguy cơ lệch tên biến secret (401 deploy).")

    if errors:
        print("JWT CLAIMS LINT - FAIL:")
        for e in errors:
            print("  x", e)
        return 1
    print(f"JWT CLAIMS LINT OK: producer phát {len(issued)} claim đúng snapshot; "
          f"{len(c.get('consumers') or {})} consumer required ⊆ issued, ACL reads đã khai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
