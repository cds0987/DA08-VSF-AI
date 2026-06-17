"""Run versioned SQL migrations for query-service."""
import asyncio
import logging
import os
from pathlib import Path

from app.infrastructure.db.dsn import to_asyncpg_dsn

logger = logging.getLogger(__name__)

# /app/app/infrastructure/db/migrate.py -> parents[3] = /app  (WORKDIR, chứa migrations/)
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

# Bảng code BẮT BUỘC phải tồn tại sau migrate. Thiếu -> fail-fast NGAY tại query-migrate
# (deploy đỏ với thông điệp rõ ràng) thay vì lỗi runtime mơ hồ (RAG 0 sources + NAK-storm).
# Sự cố 2026-06-16: user_access_profile bị quên migration -> chỉ lộ ở smoke-on-prod.
REQUIRED_TABLES = (
    "conversations",
    "messages",
    "document_access",
    "notifications",
    "user_access_profile",
)


async def _assert_required_tables(conn) -> None:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'query_svc'"
    )
    present = {r["table_name"] for r in rows}
    missing = [t for t in REQUIRED_TABLES if t not in present]
    if missing:
        raise RuntimeError(
            "MIGRATION INCOMPLETE — bảng code cần nhưng KHÔNG có sau migrate: "
            f"{missing}. Có thể quên file migration. ABORT để chặn drift "
            "(tránh NAK-storm + RAG 0 sources như sự cố 2026-06-16)."
        )


async def run_migrations(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required to run query-service migrations") from exc

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No query-service migrations found in {MIGRATIONS_DIR}")

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    try:
        await conn.execute(
            """
            CREATE SCHEMA IF NOT EXISTS query_svc;
            CREATE TABLE IF NOT EXISTS query_svc.schema_migrations (
                filename text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        for sql_file in files:
            applied = await conn.fetchval(
                "SELECT 1 FROM query_svc.schema_migrations WHERE filename = $1",
                sql_file.name,
            )
            if applied:
                logger.info("skip applied migration %s", sql_file.name)
                continue
            logger.info("apply migration %s", sql_file.name)
            async with conn.transaction():
                await conn.execute(sql_file.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO query_svc.schema_migrations (filename) VALUES ($1)",
                    sql_file.name,
                )
        await _assert_required_tables(conn)
    finally:
        await conn.close()
    logger.info("query-service migrations are current")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to run query-service migrations")
    asyncio.run(run_migrations(database_url))


if __name__ == "__main__":
    main()
