"""add admin_batch_analysis_jobs table

Revision ID: b8f3d4e5a9c2
Revises: a4f2e1b3c8d5
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b8f3d4e5a9c2'
down_revision = 'a4f2e1b3c8d5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_batch_analysis_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(length=100), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('concurrency', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('total_count', sa.Integer(), nullable=False),
        sa.Column('completed_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('failed_user_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_admin_batch_user', 'admin_batch_analysis_jobs', ['user_id'], unique=False)
    op.create_index('idx_admin_batch_status', 'admin_batch_analysis_jobs', ['status'], unique=False)
    op.create_index('idx_admin_batch_created_at', 'admin_batch_analysis_jobs', ['created_at'], unique=False)


def downgrade():
    op.drop_index('idx_admin_batch_created_at', table_name='admin_batch_analysis_jobs')
    op.drop_index('idx_admin_batch_status', table_name='admin_batch_analysis_jobs')
    op.drop_index('idx_admin_batch_user', table_name='admin_batch_analysis_jobs')
    op.drop_table('admin_batch_analysis_jobs')
