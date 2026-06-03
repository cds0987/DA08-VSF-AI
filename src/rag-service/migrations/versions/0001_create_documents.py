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
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_table("documents")
