"""Phase 1 Jobs: job_card metadata columns + job_snapshot table.

Additive only — NO drops, NO type changes, NO data mutation:
  1. ALTER job_card: add 6 NULLABLE metadata columns (job_type, scope_notes, room_count, room_types,
     floor_area_sqm, floor_area_unit_pref). All nullable ⇒ no backfill, no NOT NULL on a populated
     table ⇒ safe on every env incl. Postgres-ot-n. (floor_area_unit_pref carries server_default
     'sqm' for tidiness but is nullable regardless.)
  2. CREATE TABLE job_snapshot: brand-new table (frozen completion snapshot; versioned per completion).
     NOT-NULL columns (snapshot_version, direct_costs_total) carry server_default so the ORM/create_all
     insert path matches Alembic exactly (reconcile_d / risk #10 discipline — model authored in lockstep
     with this migration).

Model: app/models/job_card.py (JobCard metadata + JobSnapshot). JSONB columns use plain JSON on
SQLite (tests) via the model's with_variant; this migration only ever runs on Postgres.

Revision ID: add_job_metadata_snapshot
Revises: add_customer_cache
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_job_metadata_snapshot'
down_revision = 'add_customer_cache'
branch_labels = None
depends_on = None


def upgrade():
    # 1. job_card metadata (all nullable → safe on populated tables)
    with op.batch_alter_table('job_card') as batch_op:
        batch_op.add_column(sa.Column('job_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('scope_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('room_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('room_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch_op.add_column(sa.Column('floor_area_sqm', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('floor_area_unit_pref', sa.String(length=8),
                                      nullable=True, server_default='sqm'))

    # 2. job_snapshot (new table)
    op.create_table(
        'job_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_card_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('frozen_at', sa.DateTime(), nullable=True),
        sa.Column('status_at_freeze', sa.String(length=20), nullable=True),
        sa.Column('materials_cost', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('materials_sold', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('materials_profit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('labour_hours', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('labour_cost', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('labour_charged', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('labour_profit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('direct_costs_total', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('overall_profit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('labour_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('job_type', sa.String(length=50), nullable=True),
        sa.Column('room_count', sa.Integer(), nullable=True),
        sa.Column('room_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('floor_area_sqm', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_card_id'], ['job_card.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_card_id', 'snapshot_version', name='uq_job_snapshot_version'),
    )
    op.create_index(op.f('ix_job_snapshot_job_card_id'), 'job_snapshot', ['job_card_id'], unique=False)
    op.create_index(op.f('ix_job_snapshot_user_id'), 'job_snapshot', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_job_snapshot_user_id'), table_name='job_snapshot')
    op.drop_index(op.f('ix_job_snapshot_job_card_id'), table_name='job_snapshot')
    op.drop_table('job_snapshot')
    with op.batch_alter_table('job_card') as batch_op:
        batch_op.drop_column('floor_area_unit_pref')
        batch_op.drop_column('floor_area_sqm')
        batch_op.drop_column('room_types')
        batch_op.drop_column('room_count')
        batch_op.drop_column('scope_notes')
        batch_op.drop_column('job_type')
