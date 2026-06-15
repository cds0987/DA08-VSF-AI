#!/usr/bin/env python3
"""Lint Alembic migration chains across services — chặn lỗi revision TRƯỚC khi deploy.

Bắt đúng class lỗi đã gây sập production 2026-06:
  - TRÙNG revision id (vụ "hai file cùng 0004") -> alembic nhập nhằng.
  - down_revision trỏ tới revision KHÔNG tồn tại -> "Can't locate revision ...".
  - NHIỀU head (chuỗi rẽ nhánh) -> upgrade head không xác định.
  - Chu trình (cycle) trong chuỗi.

Thuần tĩnh (parse file), KHÔNG cần DB/alembic runtime. Exit 1 nếu có lỗi.
Chạy: python infra/ci/migration_lint.py [src_root]
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # tránh lỗi console cp1252 trên Windows
except Exception:
    pass

REV_RE = re.compile(r'^\s*revision(?:\s*:\s*\w+)?\s*=\s*[\'"]([^\'"]+)[\'"]', re.M)
DOWN_RE = re.compile(r'^\s*down_revision(?:\s*:[^=]+)?\s*=\s*(None|[\'"]([^\'"]+)[\'"])', re.M)


def lint_service(versions_dir: Path) -> list[str]:
    """Trả về danh sách lỗi cho 1 service (rỗng = sạch)."""
    errors: list[str] = []
    revs: dict[str, Path] = {}          # revision id -> file
    downs: dict[str, str | None] = {}   # revision id -> down_revision (None nếu gốc)
    dup: list[str] = []

    for f in sorted(versions_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        text = f.read_text(encoding="utf-8")
        m_rev = REV_RE.search(text)
        if not m_rev:
            errors.append(f"{f.name}: không tìm thấy 'revision = ...'")
            continue
        rev = m_rev.group(1)
        if rev in revs:
            dup.append(f"revision TRÙNG '{rev}': {revs[rev].name} & {f.name}")
        revs[rev] = f
        m_down = DOWN_RE.search(text)
        downs[rev] = None if (not m_down or m_down.group(1) == "None") else m_down.group(2)

    errors.extend(dup)
    if not revs:
        return errors

    # down_revision phải trỏ tới revision tồn tại
    for rev, down in downs.items():
        if down is not None and down not in revs:
            errors.append(f"'{rev}' có down_revision '{down}' KHÔNG TỒN TẠI (sẽ gây 'Can't locate revision')")

    # đúng 1 head (revision không bị ai trỏ tới làm down_revision)
    referenced = {d for d in downs.values() if d is not None}
    heads = [r for r in revs if r not in referenced]
    if len(heads) > 1:
        errors.append(f"NHIỀU head ({len(heads)}): {sorted(heads)} — chuỗi rẽ nhánh")
    elif len(heads) == 0:
        errors.append("KHÔNG có head (chuỗi có chu trình?)")

    # đúng 1 gốc + không cycle (đi ngược từ head về None)
    roots = [r for r, d in downs.items() if d is None]
    if len(roots) > 1:
        errors.append(f"NHIỀU gốc (down_revision=None): {sorted(roots)}")
    if heads and len(heads) == 1:
        seen, cur, steps = set(), heads[0], 0
        while cur is not None and cur in revs and steps <= len(revs):
            if cur in seen:
                errors.append(f"CHU TRÌNH phát hiện tại '{cur}'")
                break
            seen.add(cur)
            cur = downs.get(cur)
            steps += 1
        if cur is None and len(seen) != len(revs):
            orphan = set(revs) - seen
            errors.append(f"revision MỒ CÔI (không nối tới head): {sorted(orphan)}")
    return errors


def main() -> int:
    src_root = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
    versions_dirs = sorted(src_root.glob("*/migrations/versions"))
    if not versions_dirs:
        print(f"::warning::Không tìm thấy thư mục migrations/versions dưới {src_root}")
        return 0
    total_err = 0
    for vd in versions_dirs:
        service = vd.relative_to(src_root).parts[0]
        errs = lint_service(vd)
        if errs:
            total_err += len(errs)
            print(f"::error::[{service}] migration lint FAIL:")
            for e in errs:
                print(f"    - {e}")
        else:
            n = len([f for f in vd.glob('*.py') if f.name != '__init__.py'])
            print(f"  [{service}] OK ({n} revision, chuỗi tuyến tính, 1 head)")
    if total_err:
        print(f"\n::error::Migration lint: {total_err} lỗi -> chặn deploy. Sửa chuỗi revision trước.")
        return 1
    print("\nMigration lint: TẤT CẢ service OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
