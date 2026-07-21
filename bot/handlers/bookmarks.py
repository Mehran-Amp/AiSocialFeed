"""
SocialtoFeed — Bookmark Handler
Save posts for later reading.
Limits: Free=10, Pro=50, Premium=500
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.database import get_session
from bot.models import Bookmark, Platform, User
from bot.utils.keyboards import main_menu
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t

logger = logging.getLogger(__name__)

# v3.3: Bookmarks are UNLIMITED for all plans (Free, Pro, Premium).
# BOOKMARK_LIMITS dict removed. Limit check removed from save_bookmark().

PLATFORM_ICONS = {
    "youtube": "🎬", "twitter": "🐦", "instagram": "📸",
    "rss": "📡", "tiktok": "🎵", "linkedin": "💼",
    "reddit": "🤖", "telegram": "✈️", "bluesky": "🦋",
    "mastodon": "🐘", "threads": "🧵",
}


async def save_bookmark(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Callback when user taps 🔖 Save under a post."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return

    lang = user.language

    # Parse: "bm:save:PLATFORM:URL_HASH"
    parts = query.data.split(":", 3)
    if len(parts) < 4:
        return

    platform_str = parts[2]
    url_hash = parts[3]

    # Resolve URL from video cache or callback store
    from bot.handlers.video import _decode_url
    url = _decode_url(url_hash)
    if not url:
        await query.answer("❌ لینک منقضی شده", show_alert=True)
        return

    # v3.3: No bookmark limit — check only for duplicate
    async with get_session() as session:
        from sqlalchemy import select, func

        current_count = (await session.execute(
            select(func.count()).select_from(Bookmark)
            .where(Bookmark.user_id == user.id)
        )).scalar() or 0

        post_hash = Bookmark.make_hash(url)

        # Check duplicate
        existing = (await session.execute(
            select(Bookmark).where(
                Bookmark.user_id == user.id,
                Bookmark.post_hash == post_hash,
            )
        )).scalar_one_or_none()

        if existing:
            await query.answer(
                "✅ قبلاً ذخیره شده" if lang == "fa" else "✅ Already saved",
                show_alert=True,
            )
            return

        try:
            platform = Platform(platform_str)
        except ValueError:
            platform = Platform.RSS

        bm = Bookmark(
            user_id=user.id,
            platform=platform,
            url=url,
            post_hash=post_hash,
        )
        session.add(bm)

    await query.answer(
        "🔖 ذخیره شد!" if lang == "fa" else "🔖 Saved!",
        show_alert=False,
    )


async def show_bookmarks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show user's saved bookmarks — /saved command."""
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return

    lang = user.language

    async with get_session() as session:
        from sqlalchemy import select
        bookmarks = (await session.execute(
            select(Bookmark)
            .where(Bookmark.user_id == user.id)
            .order_by(Bookmark.created_at.desc())
            .limit(20)
        )).scalars().all()

    if not bookmarks:
        msg = (
            "🔖 <b>ذخیره‌های شما</b>\n\nهنوز چیزی ذخیره نشده.\n"
            "زیر هر پست دکمه 🔖 رو بزن تا ذخیره بشه."
        ) if lang == "fa" else (
            "🔖 <b>Your Bookmarks</b>\n\nNothing saved yet.\n"
            "Tap 🔖 under any post to save it."
        )
        await safe_send_message(update.effective_user.id, msg, parse_mode=ParseMode.HTML)
        return

    # v3.3: unlimited — show count only, no "/limit" fraction
    header = (
        f"🔖 <b>ذخیره‌های شما</b> ({len(bookmarks)} مورد)\n\n"
    ) if lang == "fa" else (
        f"🔖 <b>Your Bookmarks</b> ({len(bookmarks)} saved)\n\n"
    )

    await safe_send_message(update.effective_user.id, header, parse_mode=ParseMode.HTML)

    for bm in bookmarks:
        icon = PLATFORM_ICONS.get(bm.platform.value, "📌")
        date_str = bm.created_at.strftime("%m/%d") if bm.created_at else ""
        title = bm.title or bm.url[:60]

        text = f"{icon} <b>{title[:80]}</b>\n<i>{date_str}</i>"

        buttons = [
            [
                InlineKeyboardButton("🔗 Open", url=bm.url),
                InlineKeyboardButton(
                    "🗑 حذف" if lang == "fa" else "🗑 Remove",
                    callback_data=f"bm:del:{bm.id}"
                ),
            ]
        ]

        await safe_send_message(
            update.effective_user.id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def delete_bookmark(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Delete a saved bookmark."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return

    bm_id = int(query.data.split(":")[-1])

    async with get_session() as session:
        from sqlalchemy import select
        bm = (await session.execute(
            select(Bookmark).where(
                Bookmark.id == bm_id,
                Bookmark.user_id == user.id,
            )
        )).scalar_one_or_none()

        if bm:
            await session.delete(bm)

    await query.edit_message_text(
        "🗑 حذف شد." if user.language == "fa" else "🗑 Removed."
    )


def make_bookmark_button(platform: str, url_hash: str, lang: str) -> InlineKeyboardButton:
    """Returns a bookmark button for use in post keyboards."""
    label = "🔖 ذخیره" if lang == "fa" else "🔖 Save"
    return InlineKeyboardButton(
        label,
        callback_data=f"bm:save:{platform}:{url_hash}",
    )


def register(app: Application) -> None:
    from bot.middlewares.auth import auth_middleware

    app.add_handler(CommandHandler("saved", auth_middleware(show_bookmarks)))
    app.add_handler(CallbackQueryHandler(save_bookmark, pattern=r"^bm:save:"))
    app.add_handler(CallbackQueryHandler(delete_bookmark, pattern=r"^bm:del:"))
    logger.info("Bookmark handlers registered.")
