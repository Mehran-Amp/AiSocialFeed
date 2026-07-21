"""
SocialtoFeed — Digest Service
Generates periodic summaries of posts from all user accounts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bot.utils.translator import t

logger = logging.getLogger(__name__)


async def generate_digest(user_id: int, lang: str, hours: int = 24) -> str | None:
    """
    Generate a text digest of posts from the last N hours.
    Returns formatted HTML string or None if no posts.
    """
    from bot.database import get_session
    from sqlalchemy import select, func
    from bot.models import SentPost, Account

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_session() as session:
        rows = (await session.execute(
            select(
                Account.display_name,
                Account.platform,
                func.count(SentPost.id).label("count"),
            )
            .join(SentPost, SentPost.account_id == Account.id)
            .where(
                Account.user_id == user_id,
                SentPost.sent_at >= since,
            )
            .group_by(Account.id, Account.display_name, Account.platform)
            .order_by(func.count(SentPost.id).desc())
        )).all()

    if not rows:
        return None

    total = sum(r.count for r in rows)
    period = f"{hours}h" if hours < 24 else "24h"

    platform_icons = {
        "youtube": "🎬", "twitter": "🐦", "instagram": "📸",
        "rss": "📡", "tiktok": "🎵", "linkedin": "💼",
        "reddit": "🤖", "telegram": "✈️",
    }

    lines = [
        f"📋 <b>Summary — last {period}</b>",
        f"Total: <b>{total}</b> new posts\n",
    ]

    for row in rows[:15]:
        icon = platform_icons.get(row.platform.value, "•")
        lines.append(f"{icon} <b>{row.display_name}</b> — {row.count} post(s)")

    return "\n".join(lines)
