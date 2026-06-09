"""add benefits and performance_reviews tables + seed

Revision ID: 0002_add_benefits_performance
Revises: 0001_create_hr_schema
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_add_benefits_performance"
down_revision: Union[str, None] = "0001_create_hr_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    op.create_table(
        "benefits",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )

    op.create_table(
        "performance_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column("kpi", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reviewer_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "period", name="uq_performance_user_period"),
        schema="hr_svc",
    )
    op.create_index("idx_performance_user", "performance_reviews", ["user_id", "period"], schema="hr_svc")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.benefits (user_id, items)
            VALUES
                (:user_hr, :items_hr),
                (:user_finance, :items_finance)
            """
        ),
        {
            "user_hr": USER_HR,
            "user_finance": USER_FINANCE,
            "items_hr": '[{"name":"Bao hiem suc khoe","value":"Goi A"},{"name":"Phu cap an trua","value":"30 USD/thang"}]',
            "items_finance": '[{"name":"Bao hiem suc khoe","value":"Goi B"}]',
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.performance_reviews
                (id, user_id, period, rating, kpi, reviewer_user_id)
            VALUES
                ('perf-hr-001', :user_hr, '2026-03', 'Xuat sac', :kpi_hr, NULL),
                ('perf-fin-001', :user_finance, '2026-03', 'Dat', :kpi_finance, :user_hr)
            """
        ),
        {
            "user_hr": USER_HR,
            "user_finance": USER_FINANCE,
            "kpi_hr": '[{"name":"Tuyen dung","score":95},{"name":"Giu chan nhan su","score":90}]',
            "kpi_finance": '[{"name":"Bao cao tai chinh","score":80}]',
        },
    )


def downgrade() -> None:
    op.drop_index("idx_performance_user", table_name="performance_reviews", schema="hr_svc")
    op.drop_table("performance_reviews", schema="hr_svc")
    op.drop_table("benefits", schema="hr_svc")
