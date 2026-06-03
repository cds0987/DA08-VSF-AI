"""create documents table

Revision ID: 0001_create_documents
Revises:
Create Date: 2026-06-03

Bảng metadata document (ingestion.md §8). Index trên created_at phục vụ list_all
order-by created_at DESC + nền cho retention/prune theo thời gian (DAY0 §14).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_create_documents"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=64), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_logs_created_at", "job_logs", ["created_at"])
    op.create_index("ix_job_logs_document_id", "job_logs", ["document_id"])
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("document_name", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=64), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("claim_id", sa.String(length=255), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingest_jobs_created_at", "ingest_jobs", ["created_at"])
    op.create_index("ix_ingest_jobs_updated_at", "ingest_jobs", ["updated_at"])
    op.create_index("ix_ingest_jobs_document_id", "ingest_jobs", ["document_id"])
    op.create_index("ix_ingest_jobs_status", "ingest_jobs", ["status"])
    op.create_index("ix_ingest_jobs_claim_id", "ingest_jobs", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_claim_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_status", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_document_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_updated_at", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_created_at", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
    op.drop_index("ix_job_logs_document_id", table_name="job_logs")
    op.drop_index("ix_job_logs_created_at", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_table("documents")
