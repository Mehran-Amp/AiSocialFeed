"""v4.2.1: add fetch_interval_minutes and menu_hidden

Revision ID: 005
Revises: 004
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("fetch_interval_minutes", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("users", sa.Column("menu_hidden", sa.Boolean(), nullable=False, server_default="false"))

def downgrade():
    op.drop_column("users", "fetch_interval_minutes")
    op.drop_column("users", "menu_hidden")
