"""Regression: mọi repo asyncpg phải normalize DSN qua _asyncpg_url dùng chung.

Sự cố 2026-06-16: postgres_user_access_profile_repo tự định nghĩa _asyncpg_url
chỉ thay '+asyncpg' -> bỏ sót '+psycopg' (scheme thật trên VM) -> asyncpg.create_pool
raise 'invalid DSN ... got postgresql+psycopg' -> HR profile events NAK-loop ->
user_access_profile trống -> allowed_doc_ids rỗng -> RAG 0 sources -> DEPLOY FAIL.
"""

import pytest

from app.infrastructure.db.postgres_document_access_repo import (
    _asyncpg_url as _doc_access_url,
)
from app.infrastructure.db.postgres_user_access_profile_repo import (
    _asyncpg_url as _profile_url,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgres://u:p@h:5432/db"),
    ],
)
def test_asyncpg_url_strips_any_sqlalchemy_dialect(raw, expected):
    assert _doc_access_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql+psycopg://u:p@h:5432/db",
        "postgresql+asyncpg://u:p@h:5432/db",
        "postgresql://u:p@h:5432/db",
    ],
)
def test_profile_repo_reuses_shared_normalizer(raw):
    # user_access_profile repo PHẢI dùng đúng helper chung — không có bản local lệch.
    assert _profile_url(raw) is _doc_access_url(raw) or _profile_url(raw) == _doc_access_url(raw)
    # Quan trọng nhất: không còn '+dialect' nào sót lại để rò vào asyncpg.
    assert "+" not in _profile_url(raw).split("://", 1)[0]
