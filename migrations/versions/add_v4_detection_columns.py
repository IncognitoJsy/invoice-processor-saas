"""Add enhanced symbol detection columns

Revision ID: add_v4_detection_columns
Create Date: 2026-02-06
"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # Add colour and switch fields to symbol_template
    op.add_column('takeoff_symbol_template',
        sa.Column('description', sa.Text(), nullable=True))
    op.add_column('takeoff_symbol_template',
        sa.Column('colour', sa.String(30), nullable=True))
    op.add_column('takeoff_symbol_template',
        sa.Column('expected_text', sa.String(10), nullable=True))
    op.add_column('takeoff_symbol_template',
        sa.Column('gang_count', sa.Integer(), nullable=True))
    op.add_column('takeoff_symbol_template',
        sa.Column('is_dimmer', sa.Boolean(), nullable=True, default=False))
    
    # Add AI detection result columns to detection
    op.add_column('takeoff_symbol_detection',
        sa.Column('detected_text', sa.String(20), nullable=True))
    op.add_column('takeoff_symbol_detection',
        sa.Column('colour_detected', sa.String(30), nullable=True))
    op.add_column('takeoff_symbol_detection',
        sa.Column('gang_count_detected', sa.Integer(), nullable=True))
    op.add_column('takeoff_symbol_detection',
        sa.Column('is_dimmer_detected', sa.Boolean(), nullable=True))
    op.add_column('takeoff_symbol_detection',
        sa.Column('ai_notes', sa.Text(), nullable=True))
    op.add_column('takeoff_symbol_detection',
        sa.Column('location_description', sa.String(200), nullable=True))


def downgrade():
    op.drop_column('takeoff_symbol_template', 'description')
    op.drop_column('takeoff_symbol_template', 'colour')
    op.drop_column('takeoff_symbol_template', 'expected_text')
    op.drop_column('takeoff_symbol_template', 'gang_count')
    op.drop_column('takeoff_symbol_template', 'is_dimmer')
    
    op.drop_column('takeoff_symbol_detection', 'detected_text')
    op.drop_column('takeoff_symbol_detection', 'colour_detected')
    op.drop_column('takeoff_symbol_detection', 'gang_count_detected')
    op.drop_column('takeoff_symbol_detection', 'is_dimmer_detected')
    op.drop_column('takeoff_symbol_detection', 'ai_notes')
    op.drop_column('takeoff_symbol_detection', 'location_description')
