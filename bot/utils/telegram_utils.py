"""
SocialtoFeed — Telegram Utilities
Helper functions for sending messages, alerts, and managing bot instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config.settings import config

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

# Bot instance — set during startup
_bot: Optional[Bot] = None


def set_bot(bot: Bot) -> None:
    """Register the bot instance (called during startup)."""
    global _bot
    _bot = bot


def _validate_bot_initialized() -> None:
    """Ensure the bot is initialized before usage."""
    if _bot is None:
        raise RuntimeError("Bot not initialized. Call set_bot() first.")


def get_bot() -> Bot:
    _validate_bot_initialized()
    return _bot


# ─────────────────────────────────────────────
#  Admin Alert
# ─────────────────────────────────────────────

async def send_admin_alert(text: str) -> None:
    """
    Send a Telegram message to the admin.
    Safe — never raises, just logs if it fails.
    """
    try:
        bot = get_bot()
        await bot.send_message(
            chat_id=config.telegram.admin_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as e:
        logger.warning(f"Failed to send admin alert: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error sending admin alert: {e}")


# ─────────────────────────────────────────────
#  Safe Send (with retry)
# ─────────────────────────────────────────────

async def safe_send_message(
    chat_id: int,
    text: str,
    parse_mode: str = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    reply_markup=None,
    auto_delete_after: Optional[int] = None,
) -> Optional[object]:
    """
    Send a message with basic retry logic.
    Returns the sent message object or None if failed.
    """
    bot = get_bot()
    for attempt in range(3):
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
            if auto_delete_after and auto_delete_after > 0:
                asyncio.create_task(_delete_later(chat_id, msg.message_id, auto_delete_after))
            return msg
        except TelegramError as e:
            if attempt == 2:
                logger.error(f"Failed to send message to {chat_id}: {e}")
                return None
            await asyncio.sleep(1.5 ** attempt)
    return None


async def safe_edit(
    query,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> None:
    """
    Safely edit a callback query message.
    Silently ignores 'Message is not modified' error.
    """
    try:
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except Exception as e:
        err = str(e)
        if "message is not modified" in err.lower():
            pass  # not an error — content unchanged
        elif "message to edit not found" in err.lower():
            pass  # message was deleted — safe to ignore
        else:
            logger.warning(f"[safe_edit] {e}")
    """Delete a message after a delay (for system notifications)."""
    await asyncio.sleep(delay)
    try:
        await get_bot().delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        pass  # Already deleted or not found — ignore


# ─────────────────────────────────────────────
#  User-friendly error messages
# ─────────────────────────────────────────────

ERROR_MESSAGES: dict[str, str] = {
    "private_account":
        "🔒 این پیج/کانال خصوصیه. باید پابلیک باشه تا بشه دنبالش کرد.",
    "account_not_found":
        "❓ این اکانت پیدا نشد. شاید حذف شده یا اسمش عوض شده.",
    "invalid_url":
        "⚠️ لینک وارد شده معتبر نیست.\nمثال درست: youtube.com/c/channelname",
    "rate_limit":
        "⏳ محدودیت موقت API. ربات ۱ ساعت دیگه دوباره تلاش می‌کنه.",
    "platform_down":
        "🔧 سرویس {platform} فعلاً در دسترس نیست — مشکل از اونجاست، نه از ربات.",
    "video_too_large":
        "📦 حجم ویدیو از ۵۰ مگ بیشتره — لینک مستقیم براتون فرستادیم.",
    "ai_unavailable":
        "🤖 سرویس AI موقتاً در دسترس نیست — پست بدون پردازش ارسال شد.",
    "quota_reached":
        "📊 به سقف {limit} اکانت رسیدید. برای افزودن بیشتر، اشتراک ارتقا بدید.",
    "plan_required":
        "⭐️ این قابلیت برای پلن {plan} فعاله. برای ارتقا: /upgrade",
    "banned":
        "🚫 دسترسی شما به ربات محدود شده. برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
    "channel_permission":
        "❌ ربات دسترسی به کانال رو از دست داده. مطمئن بشید ربات ادمین کانال هست.",
    "download_timeout":
        "⏱ زمان دانلود تموم شد — لینک مستقیم براتون ارسال شد.",
    "generic":
        "⚠️ یه خطای موقت رخ داد. لطفاً چند لحظه دیگه دوباره امتحان کنید.",
}


def get_error_message(key: str, **kwargs) -> str:
    """Get a user-friendly error message, with optional format substitution."""
    template = ERROR_MESSAGES.get(key, ERROR_MESSAGES["generic"])
    try:
        return template.format(**kwargs)
    except KeyError:
        return template
