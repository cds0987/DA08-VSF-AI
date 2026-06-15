"""Run versioned SQL migrations for query-service."""
import asyncio
import logging
import os
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
    except ImportError as exc:
        raise RuntimeError("asyncpg is required to run query-service migrations") from exc

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No query-service migrations found in {MIGRATIONS_DIR}")

    conn = await asyncpg.connect(_asyncpg_dsn(database_url))
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
