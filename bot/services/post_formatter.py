"""
SocialtoFeed — Universal Post Formatter v2.0
New compact card-style format for all platforms.

Usage:
    from bot.services.post_formatter import build_caption
    caption = await build_caption(post, platform, lang, account_display_name, ai_result)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from bot.platforms.base import FetchedPost
from bot.models import SentPost
from bot.utils.translator import t

# ============================================================================
# PLATFORM CONFIGURATION
# ============================================================================

PLATFORM_CONFIG = {
}

# Alias for missing ones
PLATFORM_CONFIG["facebook"] = PLATFORM_CONFIG["rss"]
PLATFORM_CONFIG["discord"] = PLATFORM_CONFIG["rss"]
PLATFORM_CONFIG["telegram"] = PLATFORM_CONFIG["rss"]
PLATFORM_CONFIG["threads"] = PLATFORM_CONFIG["twitter"]
PLATFORM_CONFIG["mastodon"] = PLATFORM_CONFIG["twitter"]
PLATFORM_CONFIG["bluesky"] = PLATFORM_CONFIG["twitter"]

STAT_ICONS = {
    "views": "👁",
    "likes": "❤️",
    "retweets": "🔄",
    "replies": "💬",
    "shares": "↗️",
    "comments": "💬",
    "upvotes": "⬆️",
    "reactions": "👍",
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _format_time_ago(published_at: Optional[datetime]) -> str:
    """Return '2h ago', '1d ago', etc."""
    if not published_at:
        return ""
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    delta = now - published_at
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = delta.seconds // 60
    return f"{minutes}m ago" if minutes > 0 else "just now"

def _build_header(post: FetchedPost, platform: str, account_display_name: str) -> str:
    """Build Layer 1: Platform badge + Author + Metadata."""
    config = PLATFORM_CONFIG.get(platform, PLATFORM_CONFIG["rss"])
    author = post.author or account_display_name or "Unknown"

    meta_parts = []
    if post.duration:
        meta_parts.append(post.duration)
    if post.has_video:
        meta_parts.append("video")
    elif post.image_url:
        meta_parts.append("image")

    meta = " · ".join(meta_parts) if meta_parts else ""

    if meta:
        return f"[{config['badge_text']}] {author} · {meta}"
    return f"[{config['badge_text']}] {author}"

def _build_stats_pills(stats: Optional[dict], platform: str) -> str:
    """Build Layer 3: Stats as inline text (pills simulated with brackets)."""
    if not stats or not isinstance(stats, dict):
        return ""

    config = PLATFORM_CONFIG.get(platform, PLATFORM_CONFIG["rss"])
    priority = config.get("stats_priority", [])
    parts = []

    for key in priority:
        if key in stats and stats[key]:
            icon = STAT_ICONS.get(key, "•")
            parts.append(f"{icon} {stats[key]}")

    return "  ".join(parts) if parts else ""

# ============================================================================
# MAIN FORMATTER
# ============================================================================

def build_caption(
    post: FetchedPost,
    platform: str,
    lang: str = "en",
    account_display_name: str = "",
    ai_result: dict = None,
    footer: str = ""
) -> str:
    """
    Build the new compact caption following the 5-layer structure:
    Layer 1: [PLATFORM] Author · metadata
    Layer 2: Title (bold)
    Layer 3: Description OR AI Summary/Translation
    Layer 4: 👁 views  ❤️ likes  💬 comments (stats pills)
    Layer 5: 🔗 Source                          2h ago
    """
    if ai_result is None:
        ai_result = {}

    lines = []
    config = PLATFORM_CONFIG.get(platform, PLATFORM_CONFIG["rss"])

    # --- Layer 1: Header Bar ---
    header = _build_header(post, platform, account_display_name)

    category_name = post.extra.get("category_name")
    if category_name:
        header = f"📁 {category_name} | {header}"

    lines.append(header)

    # --- Layer 2: Title ---
    title = post.title or "Untitled"
    if len(title) > 200:
        title = title[:197] + "..."
    lines.append(f"<b>{title}</b>")

    # --- Spam & AI Category Tag ---
    is_spam = ai_result.get("is_spam", False)
    if is_spam:
        lines.append(f"<i>{t('post.spam_tag', lang)}</i>")

    ai_cat = ai_result.get("category")
    if ai_cat:
        lines.append(f"🏷 {ai_cat.capitalize()}")

    # --- Layer 3: Description OR AI (Summary/Translation) ---
    summary = ai_result.get("summary")
    translation = ai_result.get("translation")

    if summary or translation:
        if summary:
            lines.append(f"\n<b>{t('post.ai_summary_label', lang)}</b>\n{summary}")
        if translation:
            if not summary:
                lines.append("\n")
            lines.append(f"<b>{t('post.ai_translation_label', lang)}</b>\n{translation}")
    else:
        # Fallback to description if no AI
        if post.description and len(post.description) > 0:
            desc = post.description
            if len(desc) > 3500:
                desc = desc[:3500] + "..."
            lines.append(f"\n{desc}")

    lines.append("") # spacer before stats

    # --- Layer 4: Stats Pills ---
    stats_line = _build_stats_pills(post.stats_json, platform)
    if stats_line:
        lines.append(stats_line)

    # --- Layer 5: Divider + Footer ---
    if post.url:
        time_ago = _format_time_ago(post.published_at)
        cta_text = config["cta_fa"] if lang == "fa" else config["cta"]

        # Using HTML alignment via spacing or simple text layout for Telegram
        if time_ago:
            lines.append(f"<a href='{post.url}'><b>🔗 {cta_text}</b></a>  ·  <i>{time_ago}</i>")
        else:
            lines.append(f"<a href='{post.url}'><b>🔗 {cta_text}</b></a>")

    if footer:
        lines.append(f"\n{'─' * 16}\n{footer}")

    # Remove extra blank lines and join
    return "\n".join(l for l in lines if l is not None).replace("\n\n\n", "\n\n")
