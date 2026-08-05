"""remove_non_telegram_platforms

Revision ID: 5c1b8dbea5a5
Revises: 007
Create Date: 2026-08-05 13:17:35.026596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c1b8dbea5a5'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely remove non-telegram platform data
    op.execute("DELETE FROM sent_posts WHERE account_id IN (SELECT id FROM accounts WHERE platform != 'telegram')")
    op.execute("DELETE FROM accounts WHERE platform != 'telegram'")

    # Clean up bookmarks
    op.execute("DELETE FROM bookmarks WHERE platform != 'telegram'")

    # Clean up daily stats
    op.execute("DELETE FROM daily_stats WHERE platform != 'telegram'")

    # Clean up platform errors
    op.execute("DELETE FROM platform_errors WHERE platform != 'telegram'")

    # Clean up system logs where module matches removed platforms
    removed_modules = ('youtube', 'twitter', 'instagram', 'rss', 'tiktok', 'linkedin', 'reddit')
    op.execute(f"DELETE FROM system_logs WHERE module IN {removed_modules}")

    # Safely remove non-telegram platform data



def downgrade() -> None:
    pass
