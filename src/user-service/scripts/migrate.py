from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

try:
    import asyncpg
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: asyncpg. Install service requirements first: "
        "python -m pip install -r requirements.txt"
    ) from exc

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


SERVICE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = SERVICE_ROOT / "migrations"
ENV_FILE = SERVICE_ROOT / ".env"
DEFAULT_SCHEMA = "user_svc"
HISTORY_TABLE = "migration_history"


def main() -> int:
    _load_env()
    database_url = _get_database_url()
    schema = _get_schema_name()

    try:
        asyncio.run(run_migrations(database_url, schema))
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"[migrate] Database error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[migrate] Migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


async def run_migrations(database_url: str, schema: str) -> None:
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print(f"[migrate] No SQL files found in {MIGRATIONS_DIR}")
        return

    normalized_url = _normalize_database_url(database_url)
    print(f"[migrate] Connecting to database...")
    connection = await asyncpg.connect(dsn=normalized_url)

    try:
        await _ensure_history_table(connection, schema)
        applied = await _get_applied_migrations(connection, schema)

        for sql_file in sql_files:
            name = sql_file.name
            checksum = _sha256(sql_file)
            if name in applied:
                print(f"[migrate] SKIP {name} (already applied)")
                continue

            sql = sql_file.read_text(encoding="utf-8")
            print(f"[migrate] RUN  {name}")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    f"""
                    INSERT INTO {_qualified(schema, HISTORY_TABLE)}
                        (filename, checksum)
                    VALUES ($1, $2)
                    """,
                    name,
                    checksum,
                )
            print(f"[migrate] DONE {name}")
    finally:
        await connection.close()

    print("[migrate] All migrations are up to date.")


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ENV_FILE)
        return

    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL") or os.getenv("USER_SERVICE_DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "user")
    password = os.getenv("DB_PASSWORD", "password")
    name = os.getenv("DB_NAME", "rag_chatbot")
    return (
        "postgresql://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(name)}"
    )


def _get_schema_name() -> str:
    schema = os.getenv("MIGRATION_SCHEMA", DEFAULT_SCHEMA)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("MIGRATION_SCHEMA must be a valid PostgreSQL identifier")
    return schema


def _normalize_database_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+[A-Za-z0-9_]+://", "postgresql://", database_url)


async def _ensure_history_table(connection: asyncpg.Connection, schema: str) -> None:
    await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
    await connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(schema, HISTORY_TABLE)} (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) UNIQUE NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            executed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )


async def _get_applied_migrations(
    connection: asyncpg.Connection,
    schema: str,
) -> set[str]:
    rows = await connection.fetch(
        f"SELECT filename FROM {_qualified(schema, HISTORY_TABLE)}"
    )
    return {str(row["filename"]) for row in rows}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qualified(schema: str, table: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(table)}"


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


if __name__ == "__main__":
    raise SystemExit(main())
