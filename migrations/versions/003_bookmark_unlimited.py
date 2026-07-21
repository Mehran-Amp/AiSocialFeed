"""Set bookmark_limit = 0 (unlimited) for all plans.

v3.3 change: bookmarks are now unlimited for Free, Pro, and Premium.
0 is the sentinel value meaning "no cap enforced".

Revision ID: 003
Revises: 002
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set bookmark_limit = 0 (unlimited) for every existing plan_config row
    op.execute("UPDATE plan_configs SET bookmark_limit = 0")

    # Also update the column default so any future rows start unlimited
    op.alter_column(
        "plan_configs",
        "bookmark_limit",
        server_default="0",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Restore original limits per plan name
    op.execute("UPDATE plan_configs SET bookmark_limit = 10  WHERE plan = 'free'")
    op.execute("UPDATE plan_configs SET bookmark_limit = 100 WHERE plan = 'pro'")
    op.execute("UPDATE plan_configs SET bookmark_limit = 500 WHERE plan = 'premium'")
    op.alter_column(
        "plan_configs",
        "bookmark_limit",
        server_default="10",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
