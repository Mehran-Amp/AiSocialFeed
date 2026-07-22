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

from config import config

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

# Bot instance — set during startup
_bot: Optional[Bot] = None


def set_bot(bot: Bot) -> None:
    """Register the bot instance (called during startup)."""
    global _bot
    _bot = bot


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot not initialized. Call set_bot() first.")
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

from telegram.error import Forbidden, RetryAfter

async def safe_send_message(
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    reply_markup=None,
    auto_delete_after: Optional[int] = None,
    max_retries: int = 3,
) -> Optional[object]:
    """
    Replaces the old safe_send_message.
    Handles RetryAfter (flood control) and Forbidden (bot blocked).
    """
    bot = get_bot()
    for attempt in range(max_retries):
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
            if auto_delete_after:
                asyncio.create_task(_delete_later(chat_id, msg.message_id, auto_delete_after))
            return msg

        except RetryAfter as e:
            # Telegram flood control — must wait exactly e.retry_after seconds
            wait = e.retry_after + 1
            logger.warning(f"RetryAfter {wait}s for chat_id={chat_id}")
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
            else:
                logger.error(f"RetryAfter max retries exceeded for chat_id={chat_id}")
                return None

        except Forbidden:
            # User blocked the bot — disable their accounts
            logger.info(f"Bot blocked by user {chat_id} — disabling accounts")
            await _handle_bot_blocked(chat_id)
            return None

        except Exception as e:
            err = str(e).lower()
            if "bot was blocked" in err or "user is deactivated" in err:
                await _handle_bot_blocked(chat_id)
                return None
            if attempt == max_retries - 1:
                logger.error(f"safe_send failed for {chat_id}: {e}")
                return None
            await asyncio.sleep(1.5 ** attempt)

    return None

async def _handle_bot_blocked(telegram_id: int) -> None:
    """Pause all accounts for a user who blocked the bot."""
    try:
        from bot.database import get_session
        from bot.models import Account, User
        from sqlalchemy import select, update

        async with get_session() as session:
            user = (await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )).scalar_one_or_none()

            if user:
                await session.execute(
                    update(Account)
                    .where(Account.user_id == user.id)
                    .values(is_active=False)
                )
                logger.info(f"Disabled all accounts for blocked user {telegram_id}")
    except Exception as e:
        logger.error(f"_handle_bot_blocked failed: {e}")


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
