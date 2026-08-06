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
# Sanitize HTML to keep only Telegram-supported tags.
        from html.parser import HTMLParser
        class TelegramHTMLParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.result = []
                self.allowed_tags = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a', 'code', 'pre', 'blockquote'}
            def handle_starttag(self, tag, attrs):
                if tag == 'br':
                    self.result.append(chr(10))
                elif tag == 'p':
                    self.result.append(chr(10) + chr(10))
                elif tag in self.allowed_tags:
                    attr_str = "".join([f' {k}="{v}"' for k,v in attrs if k == 'href']) if tag == 'a' else ""
                    self.result.append(f"<{tag}{attr_str}>")
            def handle_endtag(self, tag):
                if tag in self.allowed_tags:
                    self.result.append(f"</{tag}>")
            def handle_data(self, data):
                self.result.append(data)

        parser = TelegramHTMLParser()
        parser.feed(desc)
        desc = "".join(parser.result)
        import re
        desc = re.sub(r'\n{3,}', '\n\n', desc) # normalize spacing
        if len(desc) > 3500:
            desc = desc[:3500] + "..."
        lines.append(desc.strip())

    if footer:
        lines.append("")
        lines.append(f"<i>{footer}</i>")

    return "\n".join(lines).strip()
