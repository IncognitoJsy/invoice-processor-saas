"""Add product_cache table

Revision ID: 750ad37668d5
Revises: <REPLACE_WITH_YOUR_LATEST_REVISION>
Create Date: 2026-02-16 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '750ad37668d5'
down_revision = 'merge_heads_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.String(length=200), nullable=True),
        sa.Column('code', sa.String(length=200), nullable=True),
        sa.Column('name', sa.String(length=500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('purchase_description', sa.Text(), nullable=True),
        sa.Column('purchase_price', sa.Float(), nullable=True, default=0),
        sa.Column('sale_price', sa.Float(), nullable=True, default=0),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_product_cache_user_code', 'product_cache', ['user_id', 'code'], unique=False)
    op.create_index(op.f('ix_product_cache_code'), 'product_cache', ['code'], unique=False)
    op.create_index(op.f('ix_product_cache_user_id'), 'product_cache', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_product_cache_user_code', table_name='product_cache')
    op.drop_index(op.f('ix_product_cache_code'), table_name='product_cache')
    op.drop_index(op.f('ix_product_cache_user_id'), table_name='product_cache')
    op.drop_table('product_cache')
