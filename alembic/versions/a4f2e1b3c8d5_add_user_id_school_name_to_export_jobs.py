"""Add user_id and school_name to summary_report_export_jobs

Revision ID: a4f2e1b3c8d5
Revises: 3a1c7f0b9d12
Create Date: 2026-03-27 06:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4f2e1b3c8d5"
down_revision: Union[str, None] = "3a1c7f0b9d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "summary_report_export_jobs",
        sa.Column("user_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "summary_report_export_jobs",
        sa.Column("school_name", sa.String(length=100), nullable=True),
    )
    # 补充 user_id 索引
    op.create_index(
        "idx_summary_export_user",
        "summary_report_export_jobs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_summary_export_user", table_name="summary_report_export_jobs")
    op.drop_column("summary_report_export_jobs", "school_name")
    op.drop_column("summary_report_export_jobs", "user_id")
