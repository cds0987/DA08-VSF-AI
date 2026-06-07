"""add ingest job guardrail index

Revision ID: 0002_ingest_job_guardrails
Revises: 0001_create_documents
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ingest_job_guardrails"
down_revision: Union[str, None] = "0001_create_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DUPLICATE_ACTIVE_JOB_ERROR = "superseded by migration before active-job unique index"


def _fail_duplicate_active_jobs() -> None:
    # op.execute() KHÔNG nhận bind params (đối số thứ 2 là execution_options) -> dùng
    # connection.execute() để truyền tham số an toàn, tránh nội suy chuỗi vào SQL.
    op.get_bind().execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY document_id
                        ORDER BY created_at ASC, id ASC
                    ) AS rn
                FROM ingest_jobs
                WHERE status IN ('PENDING', 'PROCESSING', 'STALE')
            )
            UPDATE ingest_jobs
            SET
                status = 'FAILED',
                claim_id = NULL,
                error_message = :error_message
            WHERE id IN (
                SELECT id
                FROM ranked
                WHERE rn > 1
            )
            """
        ),
        {"error_message": _DUPLICATE_ACTIVE_JOB_ERROR},
    )


def upgrade() -> None:
    _fail_duplicate_active_jobs()
    dialect = op.get_bind().dialect.name
    where = sa.text("status IN ('PENDING','PROCESSING','STALE')")
    kwargs = {"unique": True}
    if dialect == "postgresql":
        kwargs["postgresql_where"] = where
    elif dialect == "sqlite":
        kwargs["sqlite_where"] = where
    op.create_index(
        "ux_ingest_jobs_active_document_id",
        "ingest_jobs",
        ["document_id"],
        **kwargs,
    )


def downgrade() -> None:
    op.drop_index("ux_ingest_jobs_active_document_id", table_name="ingest_jobs")
