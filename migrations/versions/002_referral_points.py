"""Add referral_count and referral_points to users table.

Revision ID: 002
Revises: 001
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001_initial"  # must match revision string in 001_initial.py
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("referral_points", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "referral_points")
    op.drop_column("users", "referral_count")
