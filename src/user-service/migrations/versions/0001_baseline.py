"""baseline: create user_svc schema (users, refresh_tokens, audit_logs)

Phản ánh trạng thái HIỆN TẠI của models (gồm cột account_type — nuốt luôn ý nghĩa
file 001_add_users_account_type.sql cũ của runner tự chế scripts/migrate.py).

Chuyển DB cũ đang chạy (VM): chạy `alembic stamp 0001_baseline` MỘT LẦN thay vì
upgrade (bảng đã tồn tại). Bảng migration_history của runner cũ vô hại, có thể drop
tay sau khi xác nhận Alembic chạy ổn.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-12
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent trên DB đang chạy (prod tạo bảng trước khi dùng Alembic): bảng đã có
    # -> chỉ stamp version, KHÔNG tạo lại. DB mới -> tạo đầy đủ. Hết cần stamp thủ công.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    op.execute("CREATE SCHEMA IF NOT EXISTS user_svc")
    existing = set(insp.get_table_names(schema="user_svc"))

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=True),
            sa.Column("auth_provider", sa.String(20), nullable=False, server_default="local"),
            sa.Column("role", sa.String(20), nullable=False, server_default="user"),
            sa.Column("account_type", sa.String(20), nullable=False, server_default="internal"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("department", sa.String(100), nullable=False, server_default=""),
            sa.Column("failed_login_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("account_type IN ('internal', 'external')", name="ck_users_account_type"),
            sa.UniqueConstraint("email", name="uq_users_email"),
            schema="user_svc",
        )
        op.create_index("ix_user_svc_users_email", "users", ["email"], schema="user_svc")
        op.create_index("ix_user_svc_users_account_type", "users", ["account_type"], schema="user_svc")

    if "refresh_tokens" not in existing:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["user_id"], ["user_svc.users.id"], ondelete="CASCADE"),
            schema="user_svc",
        )
        op.create_index("ix_user_svc_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema="user_svc")
        op.create_index("ix_user_svc_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], schema="user_svc")

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
            schema="user_svc",
        )
        op.create_index("ix_user_svc_audit_logs_actor_id", "audit_logs", ["actor_id"], schema="user_svc")


def downgrade() -> None:
    op.drop_index("ix_user_svc_audit_logs_actor_id", table_name="audit_logs", schema="user_svc")
    op.drop_table("audit_logs", schema="user_svc")
    op.drop_index("ix_user_svc_refresh_tokens_token_hash", table_name="refresh_tokens", schema="user_svc")
    op.drop_index("ix_user_svc_refresh_tokens_user_id", table_name="refresh_tokens", schema="user_svc")
    op.drop_table("refresh_tokens", schema="user_svc")
    op.drop_index("ix_user_svc_users_account_type", table_name="users", schema="user_svc")
    op.drop_index("ix_user_svc_users_email", table_name="users", schema="user_svc")
    op.drop_table("users", schema="user_svc")
    op.execute("DROP SCHEMA IF EXISTS user_svc CASCADE")
