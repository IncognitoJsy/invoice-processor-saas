"""Add user_preferences and correction_logs tables

Revision ID: add_vtq_prefs
Revises: 750ad37668d5
Create Date: 2026-02-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_vtq_prefs'
down_revision = '750ad37668d5'
branch_labels = None
depends_on = None


def upgrade():
    # User preferences table
    op.create_table('user_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True, server_default='chat'),
        sa.Column('active', sa.Boolean(), nullable=True, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'category', 'key', name='uq_user_pref')
    )
    op.create_index(op.f('ix_user_preferences_user_id'), 'user_preferences', ['user_id'], unique=False)

    # Correction logs table
    op.create_table('correction_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('job_title', sa.String(length=200), nullable=True),
        sa.Column('room_name', sa.String(length=100), nullable=True),
        sa.Column('field_type', sa.String(length=50), nullable=False),
        sa.Column('original_value', sa.String(length=500), nullable=True),
        sa.Column('corrected_value', sa.String(length=500), nullable=True),
        sa.Column('context', sa.String(length=500), nullable=True),
        sa.Column('correction_count', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('promoted', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_correction_logs_user_id'), 'correction_logs', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_correction_logs_user_id'), table_name='correction_logs')
    op.drop_table('correction_logs')
    op.drop_index(op.f('ix_user_preferences_user_id'), table_name='user_preferences')
    op.drop_table('user_preferences')
