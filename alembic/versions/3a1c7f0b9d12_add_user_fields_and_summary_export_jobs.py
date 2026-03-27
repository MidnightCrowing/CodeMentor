"""Add user fields and summary_report_export_jobs table

Revision ID: 3a1c7f0b9d12
Revises: 2f8c9b1e4a6d
Create Date: 2026-03-26 11:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3a1c7f0b9d12"
down_revision: Union[str, None] = "2f8c9b1e4a6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("real_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("student_no", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=200), nullable=True))
    op.create_index("idx_users_student_no", "users", ["student_no"], unique=True)

    op.create_table(
        "summary_report_export_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("class_code", sa.String(length=20), nullable=True),
        sa.Column("course_name", sa.String(length=100), nullable=True),
        sa.Column("teacher_name", sa.String(length=100), nullable=True),
        sa.Column("include_text_evaluation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("result_path", sa.String(length=300), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_summary_export_status", "summary_report_export_jobs", ["status"], unique=False)
    op.create_index("idx_summary_export_created_at", "summary_report_export_jobs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_summary_export_created_at", table_name="summary_report_export_jobs")
    op.drop_index("idx_summary_export_status", table_name="summary_report_export_jobs")
    op.drop_table("summary_report_export_jobs")

    op.drop_index("idx_users_student_no", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "student_no")
    op.drop_column("users", "real_name")
