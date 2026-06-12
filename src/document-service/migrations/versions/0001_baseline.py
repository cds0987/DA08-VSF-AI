"""baseline: create doc_svc schema (documents, audit_logs)

Phản ánh trạng thái HIỆN TẠI của models (cột đã là gcs_key — nuốt luôn ý nghĩa
file 001_rename_s3_key_to_gcs_key.sql cũ).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-12
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent trên DB đang chạy (prod đã có bảng tạo tay trước khi dùng Alembic):
    # nếu bảng đã tồn tại -> CHỈ stamp version, KHÔNG tạo lại (tránh "relation already
    # exists"). DB mới -> tạo đầy đủ. Hết cần `alembic stamp` thủ công.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    op.execute("CREATE SCHEMA IF NOT EXISTS doc_svc")
    existing = set(insp.get_table_names(schema="doc_svc"))

    if "documents" not in existing:
        op.create_table(
            "documents",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column("file_type", sa.String(20), nullable=False),
            sa.Column("gcs_key", sa.String(1000), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("uploaded_by", PG_UUID(as_uuid=True), nullable=False),
            sa.Column("classification", sa.String(20), nullable=False, server_default="internal"),
            sa.Column("allowed_departments", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("allowed_user_ids", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            schema="doc_svc",
        )
        op.create_index("ix_doc_svc_documents_status", "documents", ["status"], schema="doc_svc")
        op.create_index("ix_doc_svc_documents_uploaded_by", "documents", ["uploaded_by"], schema="doc_svc")

    if "audit_logs" not in existing:
        op.create_table(
            "audit_logs",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("actor_id", PG_UUID(as_uuid=True), nullable=False),
            sa.Column("actor_role", sa.String(50), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("resource_type", sa.String(100), nullable=True),
            sa.Column("resource_id", PG_UUID(as_uuid=True), nullable=True),
            sa.Column("detail", JSONB, nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema="doc_svc",
        )
        op.create_index("ix_doc_svc_audit_logs_actor_id", "audit_logs", ["actor_id"], schema="doc_svc")


def downgrade() -> None:
    op.drop_index("ix_doc_svc_audit_logs_actor_id", table_name="audit_logs", schema="doc_svc")
    op.drop_table("audit_logs", schema="doc_svc")
    op.drop_index("ix_doc_svc_documents_uploaded_by", table_name="documents", schema="doc_svc")
    op.drop_index("ix_doc_svc_documents_status", table_name="documents", schema="doc_svc")
    op.drop_table("documents", schema="doc_svc")
    op.execute("DROP SCHEMA IF EXISTS doc_svc CASCADE")
