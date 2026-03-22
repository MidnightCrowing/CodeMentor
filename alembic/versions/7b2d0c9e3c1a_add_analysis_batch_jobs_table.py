"""Add analysis_batch_jobs table

Revision ID: 7b2d0c9e3c1a
Revises: 15411dafef04
Create Date: 2026-03-22 11:15:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b2d0c9e3c1a"
down_revision: Union[str, None] = "15411dafef04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_batch_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=True),
        sa.Column("input_file_id", sa.String(length=100), nullable=True),
        sa.Column("output_file_id", sa.String(length=100), nullable=True),
        sa.Column("error_file_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_batch_date", "analysis_batch_jobs", ["date"], unique=False)
    op.create_index("idx_batch_status", "analysis_batch_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_batch_status", table_name="analysis_batch_jobs")
    op.drop_index("idx_batch_date", table_name="analysis_batch_jobs")
    op.drop_table("analysis_batch_jobs")
