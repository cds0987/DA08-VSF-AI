"""Chuẩn hóa DSN tập trung — NGUỒN DUY NHẤT cho việc đổi scheme SQLAlchemy -> asyncpg.

Bối cảnh: env build trong docker-compose dùng scheme SQLAlchemy (postgresql+psycopg://,
postgresql+asyncpg://, ...) cho thống nhất giữa các service. Nhưng query-service nối DB
bằng asyncpg THÔ — driver này CHỈ nhận postgresql:// / postgres://. Trước đây mỗi repo tự
cắt chuỗi (3+ bản sao, 1 bản chỉ xử lý +asyncpg -> sót +psycopg -> sự cố 2026-06-16).
Giờ normalize ĐÚNG MỘT LẦN ở đây; repo nhận DSN đã sạch, không string-surgery."""

import re

_DIALECT_RE = re.compile(r"^postgresql\+[a-z0-9_]+://")


def to_asyncpg_dsn(url: str) -> str:
    """Bỏ MỌI dialect SQLAlchemy (+psycopg/+asyncpg/...) -> scheme asyncpg chấp nhận."""
    return _DIALECT_RE.sub("postgresql://", url, count=1)
