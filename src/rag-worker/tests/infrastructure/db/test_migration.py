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
    assert "ix_ingest_jobs_unpublished_terminal" in ingest_job_index_names
    ingest_job_columns = {column["name"] for column in inspector.get_columns("ingest_jobs")}
    assert "status_published_at" in ingest_job_columns

    command.downgrade(cfg, "base")
    assert "documents" not in sa.inspect(sa.create_engine(url)).get_table_names()


def test_migration_upgrade_deduplicates_active_jobs_before_unique_index(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'm_dupe.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "0001_create_documents")

    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO ingest_jobs (
                    id, document_id, document_name, file_type, source_uri, markdown,
                    artifact_uri, correlation_id, status, claim_id, attempt, chunk_count,
                    error_message, created_at, updated_at
                ) VALUES
                    ('job-1', 'doc-1', 'Policy', 'md', 'local://doc-1', NULL, NULL, 'cid-1',
                     'PENDING', NULL, 0, 0, NULL, '2026-06-01T00:00:00+00:00', '2026-06-01T00:00:00+00:00'),
                    ('job-2', 'doc-1', 'Policy', 'md', 'local://doc-1', NULL, NULL, 'cid-2',
                     'PROCESSING', 'claim-2', 1, 0, NULL, '2026-06-02T00:00:00+00:00', '2026-06-02T00:00:00+00:00')
                """
            )
        )

    command.upgrade(cfg, "head")

    with engine.begin() as conn:
        rows = conn.execute(
            sa.text(
                """
                SELECT id, status, claim_id, error_message
                FROM ingest_jobs
                WHERE document_id = 'doc-1'
                ORDER BY created_at ASC, id ASC
                """
            )
        ).all()

    assert rows[0] == ("job-1", "PENDING", None, None)
    assert rows[1] == (
        "job-2",
        "FAILED",
        None,
        "superseded by migration before active-job unique index",
    )


def test_migration_upgrade_adds_status_publish_tracking_column_and_index(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'm_outbox.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "0002_ingest_job_guardrails")

    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO ingest_jobs (
                    id, document_id, document_name, file_type, source_uri, markdown,
                    artifact_uri, correlation_id, status, claim_id, attempt, chunk_count,
                    error_message, created_at, updated_at
                ) VALUES
                    ('job-1', 'doc-1', 'Policy', 'md', 'local://doc-1', NULL, NULL, 'cid-1',
                     'COMPLETED', NULL, 1, 4, NULL, '2026-06-01T00:00:00+00:00', '2026-06-01T00:00:00+00:00')
                """
            )
        )

    command.upgrade(cfg, "head")

    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("ingest_jobs")}
    assert "status_published_at" in columns
    index_names = {index["name"] for index in inspector.get_indexes("ingest_jobs")}
    assert "ix_ingest_jobs_unpublished_terminal" in index_names

    with engine.begin() as conn:
        row = conn.execute(
            sa.text(
                "SELECT status_published_at FROM ingest_jobs WHERE id = 'job-1'"
            )
        ).one()

    assert row[0] is None
