#!/usr/bin/env python3
"""GATE HTTP: ép client (dict thô) khớp server Pydantic của hr-service
(infra/http/hr-service-contract.yaml). Bắt drift ÂM THẦM: server đổi/thêm field BẮT BUỘC ->
client thiếu -> 422 lúc chạy (vỡ luồng đơn nghỉ). Thuần tĩnh (AST). Lệch = exit 1.

Cơ chế:
  server_model (Pydantic) -> field 'required' = AnnAssign KHÔNG có default value
                            (vd `user_id: str`); có default (`reason: str = ""`,
                            `idempotency_key: Optional[str] = None`) -> optional.
  client fn -> gom mọi string-literal dict key.
  GATE: required ⊆ client_keys (mọi client gửi đủ field bắt buộc).
        client_key ∉ all_fields -> CẢNH BÁO (Pydantic bỏ qua extra; không fatal).
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
CONTRACT = ROOT / "infra" / "http" / "hr-service-contract.yaml"


def _parse(rel: str) -> ast.AST | None:
    p = ROOT / rel
    return ast.parse(p.read_text(encoding="utf-8")) if p.exists() else None


def _model_fields(tree: ast.AST, model: str) -> tuple[set[str], set[str]] | None:
    """(required, all_fields) của 1 Pydantic model. required = AnnAssign không default."""
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == model:
            required: set[str] = set()
            allf: set[str] = set()
            for stmt in n.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    name = stmt.target.id
                    if name.startswith("_"):
                        continue
                    allf.add(name)
                    if stmt.value is None:           # KHÔNG có default -> required
                        required.add(name)
            return required, allf
    return None


def _fn_dict_keys(tree: ast.AST, fn: str) -> set[str] | None:
    """Mọi string-literal dict key trong FunctionDef tên=fn (None nếu không thấy fn)."""
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn:
            keys: set[str] = set()
            for d in ast.walk(n):
                if isinstance(d, ast.Dict):
                    for k in d.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
            return keys
    return None


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML chưa cài"); return 2
    c = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    errors: list[str] = []
    warns: list[str] = []
    checked = 0

    for ep, spec in (c.get("endpoints") or {}).items():
        stree = _parse(spec["server_file"])
        if stree is None:
            errors.append(f"[{ep}] server_file không tồn tại: {spec['server_file']}"); continue
        mf = _model_fields(stree, spec["server_model"])
        if mf is None:
            errors.append(f"[{ep}] KHÔNG thấy Pydantic model {spec['server_model']!r} (ref cũ?)"); continue
        required, allf = mf

        for cl in spec.get("clients") or []:
            ctree = _parse(cl["file"])
            if ctree is None:
                errors.append(f"[{ep}] client_file không tồn tại: {cl['file']}"); continue
            keys = _fn_dict_keys(ctree, cl["fn"])
            if keys is None:
                errors.append(f"[{ep}] KHÔNG thấy client fn {cl['fn']!r} trong {cl['file']} (ref cũ?)"); continue
            missing = required - keys
            if missing:
                errors.append(f"[{ep}] client {cl['fn']} ({spec['method']} {spec['path']}) THIẾU "
                              f"field bắt buộc {sorted(missing)} -> 422 lúc chạy. Server model "
                              f"{spec['server_model']} yêu cầu {sorted(required)}.")
            extra = keys - allf
            if extra:
                warns.append(f"[{ep}] client {cl['fn']} gửi field NGOÀI model {sorted(extra)} "
                             f"(Pydantic bỏ qua extra — kiểm tra gõ nhầm tên field).")
            checked += 1

    for w in warns:
        print("  ! ", w)
    if errors:
        print("HTTP CONTRACT LINT - FAIL:")
        for e in errors:
            print("  x", e)
        return 1
    print(f"HTTP CONTRACT LINT OK: {len(c.get('endpoints') or {})} endpoint, {checked} client "
          "gửi đủ field bắt buộc theo server Pydantic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
