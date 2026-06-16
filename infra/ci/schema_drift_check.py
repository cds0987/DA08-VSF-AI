#!/usr/bin/env python3
"""Chặn DRIFT giữa CODE và MIGRATION cho query-service — thuần tĩnh, không cần DB.

Bắt đúng class lỗi sự cố 2026-06-16: code đọc/ghi `query_svc.user_access_profile`
NHƯNG không file migration nào tạo bảng -> runtime lỗi 'relation does not exist' ->
NATS NAK-storm -> RAG 0 sources -> DEPLOY FAIL. Loại lỗi này 3 tầng CI cũ đều lọt
(unit mock repo; e2e không kích hoạt đường ghi; migrator không validate).

Cơ chế: gom mọi bảng code tham chiếu (FROM/INTO/UPDATE/JOIN query_svc.<tên>) trong
app/, so với bảng được CREATE TABLE trong migrations/*.sql (+ bảng bootstrap migrator
tự tạo). Code tham chiếu bảng không ai tạo -> exit 1.

Chạy: python infra/ci/schema_drift_check.py [query_service_root]
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCHEMA = "query_svc"
# Bảng migrator tạo inline (không qua file .sql) — coi như đã định nghĩa.
BOOTSTRAP_TABLES = {"schema_migrations"}

# Tham chiếu bảng trong SQL nhúng: sau FROM/INTO/UPDATE/JOIN + "query_svc.<tên>".
REF_RE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+" + re.escape(SCHEMA) + r"\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(SCHEMA) + r"\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)


def _scan(paths, pattern) -> set[str]:
    found: set[str] = set()
    for p in paths:
        try:
            found |= {m.lower() for m in pattern.findall(p.read_text(encoding="utf-8"))}
        except (OSError, UnicodeDecodeError):
            continue
    return found


def check(root: Path) -> list[str]:
    app_py = list((root / "app").rglob("*.py"))
    migr_sql = list((root / "migrations").glob("*.sql"))
    if not migr_sql:
        return [f"Không thấy migrations/*.sql trong {root}"]

    referenced = _scan(app_py, REF_RE)
    defined = _scan(migr_sql, CREATE_RE) | BOOTSTRAP_TABLES
    missing = sorted(referenced - defined)
    return [
        f"Bảng {SCHEMA}.{t} được code THAM CHIẾU nhưng KHÔNG migration nào tạo "
        f"(quên file migration?)."
        for t in missing
    ]


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/query-service")
    errors = check(root)
    if errors:
        print("SCHEMA DRIFT — code <-> migration KHÔNG khớp:")
        for e in errors:
            print(f"  ❌ {e}")
        print("\nThêm file migration tạo bảng còn thiếu rồi chạy lại.")
        return 1
    print(f"schema-drift OK: mọi bảng {SCHEMA}.* code tham chiếu đều có migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
