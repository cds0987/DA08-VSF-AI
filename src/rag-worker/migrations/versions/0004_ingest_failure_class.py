"""add ingest failure classification fields

Revision ID: 0004_ingest_failure_class
Revises: 0003_doc_status_outbox
Create Date: 2026-06-07

NOTE: revision id giữ <= 32 ký tự vì cột alembic_version.version_num là VARCHAR(32);
id dài hơn sẽ fail trên Postgres (StringDataRightTruncation), SQLite không enforce.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ingest_failure_class"
down_revision: Union[str, None] = "0003_doc_status_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("error_class", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ingest_jobs",
        sa.Column(
            "reconcile_attempt",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "reconcile_attempt")
    op.drop_column("ingest_jobs", "error_class")
