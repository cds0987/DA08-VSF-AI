from pathlib import Path

import pytest

pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

RAG_ROOT = Path(__file__).resolve().parents[3]  # .../src/rag-service


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(RAG_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAG_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_migration_upgrade_creates_metadata_and_job_tables(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "head")

    inspector = sa.inspect(sa.create_engine(url))
    assert "documents" in inspector.get_table_names()
    assert "job_logs" in inspector.get_table_names()
    assert "ingest_jobs" in inspector.get_table_names()
    index_names = {index["name"] for index in inspector.get_indexes("documents")}
    assert "ix_documents_created_at" in index_names
    job_log_index_names = {index["name"] for index in inspector.get_indexes("job_logs")}
    assert "ix_job_logs_created_at" in job_log_index_names
    assert "ix_job_logs_document_id" in job_log_index_names
    ingest_job_index_names = {
        index["name"] for index in inspector.get_indexes("ingest_jobs")
    }
    assert "ix_ingest_jobs_created_at" in ingest_job_index_names
    assert "ix_ingest_jobs_updated_at" in ingest_job_index_names
    assert "ix_ingest_jobs_document_id" in ingest_job_index_names
    assert "ix_ingest_jobs_status" in ingest_job_index_names
    assert "ix_ingest_jobs_claim_id" in ingest_job_index_names
    assert "ux_ingest_jobs_active_document_id" in ingest_job_index_names

    command.downgrade(cfg, "base")
    assert "documents" not in sa.inspect(sa.create_engine(url)).get_table_names()
