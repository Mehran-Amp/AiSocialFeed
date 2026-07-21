"""v4.2: add last_feed_viewed_at and referral_milestones_claimed

Revision ID: 004
Revises: 003
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("last_feed_viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("referral_milestones_claimed", sa.Integer(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("users", "last_feed_viewed_at")
    op.drop_column("users", "referral_milestones_claimed")
