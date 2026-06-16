"""Regression: chuẩn hóa DSN tập trung — 1 implementation duy nhất.

Sự cố 2026-06-16: postgres_user_access_profile_repo tự định nghĩa _asyncpg_url chỉ thay
'+asyncpg' -> bỏ sót '+psycopg' (scheme thật trên VM) -> asyncpg.create_pool raise
'invalid DSN ... got postgresql+psycopg' -> HR profile events NAK-loop -> bảng trống ->
allowed_doc_ids/department hỏng. Sau đó chuẩn hóa tập trung qua app.infrastructure.db.dsn:
config.asyncpg_dsn dùng nó, mọi repo dùng nó -> không còn bản sao lệch.
"""

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.db.dsn import to_asyncpg_dsn


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgres://u:p@h:5432/db"),
    ],
)
def test_to_asyncpg_dsn_strips_any_dialect(raw, expected):
    assert to_asyncpg_dsn(raw) == expected
    # idempotent: chạy lại trên DSN đã sạch không đổi gì.
    assert to_asyncpg_dsn(to_asyncpg_dsn(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql+psycopg://u:p@h:5432/db",
        "postgresql+asyncpg://u:p@h:5432/db",
        "postgresql://u:p@h:5432/db",
    ],
)
def test_settings_asyncpg_dsn_is_clean(raw):
    s = Settings(database_url=raw)
    dsn = s.asyncpg_dsn
    # Property phải trả DSN sạch (không còn '+dialect' trong scheme) — repo tin tưởng input này.
    assert dsn is not None
    assert "+" not in dsn.split("://", 1)[0]
    assert dsn == to_asyncpg_dsn(raw)


def test_settings_asyncpg_dsn_none_when_unset():
    assert Settings(database_url=None).asyncpg_dsn is None
