"""Add VTQ jobs and transcriptions tables

Revision ID: add_vtq_jobs
Revises: add_vtq_prefs
Create Date: 2026-02-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_vtq_jobs'
down_revision = 'add_vtq_prefs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vtq_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('client_name', sa.String(length=300), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('accounting_project_id', sa.String(length=200), nullable=True),
        sa.Column('accounting_project_name', sa.String(length=300), nullable=True),
        sa.Column('accounting_source', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='draft'),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('match_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('parsed_at', sa.DateTime(), nullable=True),
        sa.Column('matched_at', sa.DateTime(), nullable=True),
        sa.Column('quoted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vtq_jobs_user_id'), 'vtq_jobs', ['user_id'], unique=False)

    op.create_table('vtq_transcriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('source_filename', sa.String(length=300), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_parsed', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('parsed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['vtq_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vtq_transcriptions_job_id'), 'vtq_transcriptions', ['job_id'], unique=False)
    op.create_index(op.f('ix_vtq_transcriptions_user_id'), 'vtq_transcriptions', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_vtq_transcriptions_user_id'), table_name='vtq_transcriptions')
    op.drop_index(op.f('ix_vtq_transcriptions_job_id'), table_name='vtq_transcriptions')
    op.drop_table('vtq_transcriptions')
    op.drop_index(op.f('ix_vtq_jobs_user_id'), table_name='vtq_jobs')
    op.drop_table('vtq_jobs')
