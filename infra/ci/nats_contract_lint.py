#!/usr/bin/env python3
"""GATE NATS: ép publisher/consumer + subjects.md khớp hợp đồng máy (event-contracts.yaml).

Bắt đúng class lỗi seam async vốn IM LẶNG (không compile-error, không test đơn nào đỏ):
  - publisher bỏ/đổi 1 business field -> consumer xử sai (vd doc.status -> doc kẹt; profile
    thiếu field -> ACL sai).
  - consumer 'require' field mà contract không đảm bảo -> NAK-storm / drop.
  - subjects.md (hợp đồng người đọc) lệch code.

Thuần tĩnh (AST + parse markdown), KHÔNG cần hạ tầng / import service -> chạy như migration_lint.
Lệch = exit 1 (chặn build+deploy).

Cách kiểm (per event):
  publisher: tại `publisher_marker` (Call/FunctionDef), gom string-literal dict key ->
             business_required PHẢI ⊆ key đó (publisher gửi đủ).
  consumer : tại `consumer_markers` (FunctionDef/ClassDef), gom field 'required' =
             _required_str(_, "K") + payload["K"] -> PHẢI ⊆ (meta ∪ required ∪ optional).
  subjects.md: "Required fields:" của mỗi subject PHẢI == sorted(meta + business_required).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:  # console Windows (cp1252) không in được tiếng Việt; CI Linux đã utf-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "infra" / "nats" / "event-contracts.yaml"
SUBJECTS_MD = ROOT / "infra" / "nats" / "subjects.md"

_PAYLOAD_NAMES = {"payload", "p", "raw", "data", "msg", "event", "ev"}


# ───────────────────────── AST helpers ─────────────────────────
def _marker_nodes(tree: ast.AST, marker: str) -> list[ast.AST]:
    """MỌI node liên quan marker: FunctionDef/ClassDef tên=marker (payload dựng trong hàm,
    vd build_user_event) + Call tới hàm/method tên=marker (payload là arg, vd
    publish_doc_ingest({...})). Union -> bỏ qua stub Protocol rỗng, gom đúng nơi có dict."""
    nodes: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == marker:
            nodes.append(node)
        elif isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "attr", None) or getattr(f, "id", None)) == marker:
                nodes.append(node)
    return nodes


def _dict_string_keys(node: ast.AST) -> set[str]:
    """Mọi string-literal key của MỌI dict literal bên trong node."""
    keys: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _required_field_accesses(node: ast.AST) -> set[str]:
    """Field consumer coi là BẮT BUỘC: _required_str(_, 'K') + payload['K'] (subscript const)."""
    req: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            fname = getattr(f, "attr", None) or getattr(f, "id", None)
            if fname == "_required_str" and len(n.args) >= 2:
                a = n.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    req.add(a.value)
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in _PAYLOAD_NAMES:
            s = n.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                req.add(s.value)
    return req


def _parse(file_rel: str) -> ast.AST | None:
    p = ROOT / file_rel
    if not p.exists():
        return None
    return ast.parse(p.read_text(encoding="utf-8"))


# ───────────────────────── subjects.md ─────────────────────────
def _subjects_md_required() -> dict[str, set[str]]:
    """subject -> tập field ở dòng 'Required fields:' của section chứa subject (backtick)."""
    if not SUBJECTS_MD.exists():
        return {}
    out: dict[str, set[str]] = {}
    lines = SUBJECTS_MD.read_text(encoding="utf-8").splitlines()
    cur_subjects: list[str] = []
    for line in lines:
        if line.startswith("## "):
            cur_subjects = re.findall(r"`([a-z][a-z._]+)`", line)
        m = re.match(r"\s*Required fields:\s*(.+)$", line)
        if m and cur_subjects:
            fields = set(re.findall(r"`([a-zA-Z_][\w]*)`", m.group(1)))
            for s in cur_subjects:
                out.setdefault(s, fields)
    return out


# ───────────────────────── main ─────────────────────────
def main() -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML chưa cài"); return 2
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    events: dict = contract.get("events") or {}
    md_required = _subjects_md_required()
    errors: list[str] = []
    checked = 0

    for subject, spec in events.items():
        meta = set(spec.get("meta") or [])
        req = set(spec.get("business_required") or [])
        opt = set(spec.get("business_optional") or [])
        allowed = meta | req | opt

        # 1) PUBLISHER gửi đủ business_required
        ptree = _parse(spec["publisher_file"])
        if ptree is None:
            errors.append(f"[{subject}] publisher_file không tồn tại: {spec['publisher_file']}")
        else:
            mnodes = _marker_nodes(ptree, spec["publisher_marker"])
            if not mnodes:
                errors.append(f"[{subject}] KHÔNG thấy publisher_marker {spec['publisher_marker']!r} "
                              f"trong {spec['publisher_file']} (ref cũ?)")
            else:
                keys: set[str] = set()
                for mn in mnodes:
                    keys |= _dict_string_keys(mn)
                missing = req - keys
                if missing:
                    errors.append(f"[{subject}] publisher ({spec['publisher_marker']}) THIẾU "
                                  f"business_required {sorted(missing)} -> consumer sẽ xử sai.")
                checked += 1

        # 2) CONSUMER không require field ngoài contract
        for cfile, cmarker in zip(spec.get("consumer_files", []), spec.get("consumer_markers", [])):
            ctree = _parse(cfile)
            if ctree is None:
                errors.append(f"[{subject}] consumer_file không tồn tại: {cfile}")
                continue
            cnodes = _marker_nodes(ctree, cmarker)
            if not cnodes:
                errors.append(f"[{subject}] KHÔNG thấy consumer_marker {cmarker!r} trong {cfile} (ref cũ?)")
                continue
            creq: set[str] = set()
            for cn in cnodes:
                creq |= _required_field_accesses(cn)
            extra = creq - allowed
            if extra:
                errors.append(f"[{subject}] consumer ({cmarker}) REQUIRE field ngoài hợp đồng "
                              f"{sorted(extra)} -> publisher không đảm bảo gửi -> NAK/drop. "
                              f"Thêm vào business_required/optional hoặc đừng require.")

        # 3) subjects.md khớp (giữ hợp đồng người đọc honest)
        if subject in md_required:
            want = meta | req
            got = md_required[subject]
            if want != got:
                errors.append(f"[{subject}] subjects.md 'Required fields' LỆCH yaml: "
                              f"thiếu {sorted(want - got)} | dư {sorted(got - want)}")
        else:
            errors.append(f"[{subject}] subjects.md KHÔNG có 'Required fields' cho subject này")

    if errors:
        print("NATS CONTRACT LINT - FAIL:")
        for e in errors:
            print("  x", e)
        return 1
    print(f"NATS CONTRACT LINT OK: {len(events)} event, {checked} publisher khớp business_required, "
          "consumer ⊆ contract, subjects.md đồng bộ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
