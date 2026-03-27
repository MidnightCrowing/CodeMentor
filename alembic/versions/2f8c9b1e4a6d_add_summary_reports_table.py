"""Add summary_reports table

Revision ID: 2f8c9b1e4a6d
Revises: 7b2d0c9e3c1a
Create Date: 2026-03-26 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2f8c9b1e4a6d"
down_revision: Union[str, None] = "7b2d0c9e3c1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "summary_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("end_date", sa.String(length=10), nullable=False),
        sa.Column("report_text", sa.Text(), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "start_date", "end_date", name="uq_summary_report_dim"),
    )
    op.create_index("idx_summary_report_user", "summary_reports", ["user_id"], unique=False)
    op.create_index("idx_summary_report_range", "summary_reports", ["start_date", "end_date"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_summary_report_range", table_name="summary_reports")
    op.drop_index("idx_summary_report_user", table_name="summary_reports")
    op.drop_table("summary_reports")
