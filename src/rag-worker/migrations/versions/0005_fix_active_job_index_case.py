"""fix active ingest job index predicate case

Revision ID: 0005_fix_active_job_index_case
Revises: 0004_ingest_failure_class
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_fix_active_job_index_case"
down_revision: Union[str, None] = "0004_ingest_failure_class"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ux_ingest_jobs_active_document_id", table_name="ingest_jobs")
    dialect = op.get_bind().dialect.name
    where = sa.text("status IN ('pending','processing','stale')")
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
    # CẢNH BÁO: downgrade khôi phục predicate chữ HOA — đây là bản LỖI (status thực tế
    # lưu lowercase 'pending'/'processing'/'stale' nên index phủ 0 row → mất dedup active-job).
    # Giữ đúng ngữ nghĩa alembic (revert về schema trước 0005); chỉ dùng khi rollback toàn bộ.
    op.drop_index("ux_ingest_jobs_active_document_id", table_name="ingest_jobs")
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
