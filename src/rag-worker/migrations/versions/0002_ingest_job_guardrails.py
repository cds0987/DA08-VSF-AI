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


def upgrade() -> None:
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
