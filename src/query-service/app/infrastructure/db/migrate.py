"""Chạy migrations/*.sql lúc khởi động query-service (idempotent, CREATE ... IF NOT EXISTS).

query-service không dùng alembic; schema query_svc tạo bằng SQL thuần. Trước đây không
ai chạy file này -> bảng query_svc.* không tồn tại -> mọi endpoint chạm DB trả 500.
Chạy on-startup, non-fatal: lỗi -> log ERROR, không chặn app boot.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# /app/app/infrastructure/db/migrate.py -> parents[3] = /app  (WORKDIR, chứa migrations/)
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _asyncpg_dsn(url: str) -> str:
    """asyncpg chỉ nhận scheme postgresql:// — bỏ dialect SQLAlchemy (+psycopg/+asyncpg)."""
    return re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", url, count=1)


async def run_migrations(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg không có, bỏ qua migrations")
        return

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        logger.warning("không thấy migration nào trong %s", MIGRATIONS_DIR)
        return

    conn = await asyncpg.connect(_asyncpg_dsn(database_url))
    try:
        for sql_file in files:
            logger.info("apply migration %s", sql_file.name)
            await conn.execute(sql_file.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    logger.info("migrations applied: %d file", len(files))
