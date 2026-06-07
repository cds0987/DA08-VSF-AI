"""add doc.status publication tracking

Revision ID: 0003_doc_status_outbox
Revises: 0002_ingest_job_guardrails
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_doc_status_outbox"
down_revision: Union[str, None] = "0002_ingest_job_guardrails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("status_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    dialect = op.get_bind().dialect.name
    where = sa.text("status IN ('COMPLETED','FAILED') AND status_published_at IS NULL")
    kwargs = {}
    if dialect == "postgresql":
        kwargs["postgresql_where"] = where
    elif dialect == "sqlite":
        kwargs["sqlite_where"] = where
    op.create_index(
        "ix_ingest_jobs_unpublished_terminal",
        "ingest_jobs",
        ["updated_at"],
        **kwargs,
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_unpublished_terminal", table_name="ingest_jobs")
    op.drop_column("ingest_jobs", "status_published_at")
