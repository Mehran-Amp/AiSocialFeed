"""
SocialtoFeed — Universal Post Formatter v2.0
New compact card-style format for Telegram.
"""

from __future__ import annotations

from bot.platforms.base import FetchedPost
from bot.utils.translator import t

def build_caption(
    post: FetchedPost,
    platform: str,
    lang: str = "en",
    account_display_name: str = "",
    ai_result: dict = None,
    footer: str = ""
) -> str:
    if ai_result is None:
        ai_result = {}

    lines = []

    # 1. Header Format
    channel_name = account_display_name or post.author or "Unknown Channel"
    channel_url = None
    if post.url:
        import re
        match = re.search(r'(https://t\.me/[^/]+)', post.url)
        if match:
            channel_url = match.group(1)

    if channel_url:
        lines.append(f"📢 <a href='{channel_url}'>{channel_name}</a>")
    else:
        lines.append(f"📢 {channel_name}")

    lines.append("")

    # Replace body with AI if provided, else use original description (preserving HTML)
    summary = ai_result.get("summary")
    translation = ai_result.get("translation")

    if summary or translation:
        if summary:
            lines.append(f"<b>{t('post.ai_summary_label', lang)}</b>\n{summary}")
        if translation:
            if summary:
                lines.append("")
            lines.append(f"<b>{t('post.ai_translation_label', lang)}</b>\n{translation}")
    else:
        # Original post text exactly as published, preserving all formatting
        # Telegram native tags like <b>, <i>, <a>, <code>, <pre> are allowed.
        # We need to be careful with unsupported HTML from RSSHub though.
        desc = post.description or post.title or ""

        # We might need to sanitize unsupported RSS HTML into Telegram HTML here,
        # but the prompt specifically says "preserving all formatting (bold, links, mentions, HTML/Markdown)".
        # We will assume `description` is already acceptable or we can just pass it directly.
        # Often RSSHub includes <img ...> and <video ...> in description, which Telegram API rejects.
        # Let's strip <img...>, <video...>, <br> ->
, and <p> ->
.
        import re
        desc = re.sub(r'<br\s*/?>', '\n', desc)
        desc = re.sub(r'</p>', '\n\n', desc)
        desc = re.sub(r'<p[^>]*>', '', desc)
        desc = re.sub(r'<img[^>]*>', '', desc)
        desc = re.sub(r'<video[^>]*>.*?</video>', '', desc, flags=re.DOTALL)
        desc = re.sub(r'<iframe[^>]*>.*?</iframe>', '', desc, flags=re.DOTALL)

        if len(desc) > 3500:
            desc = desc[:3500] + "..."

        lines.append(desc.strip())

    if footer:
        lines.append("")
        lines.append(f"<i>{footer}</i>")

    return "\n".join(lines).strip()
