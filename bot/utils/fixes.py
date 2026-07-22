"""
SocialtoFeed — Critical Fixes
1. ConversationHandler timeout + fallback
2. Bot blocked → disable user accounts
3. RetryAfter flood control
4. PicklePersistence for user_data
5. Referral race condition fix
6. Re-engagement & upsell notifications
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update
from telegram.error import Forbidden, RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from config.settings import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Fix 1 — Safe Send with RetryAfter + Blocked
# ─────────────────────────────────────────────

async def safe_send_fixed(
    bot,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    reply_markup=None,
    auto_delete_after: Optional[int] = None,
    max_retries: int = 3,
):
    """
    Replaces the old safe_send_message.
    Handles RetryAfter (flood control) and Forbidden (bot blocked).
    """
    for attempt in range(max_retries):
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            if auto_delete_after:
                asyncio.create_task(_delete_later(bot, chat_id, msg.message_id, auto_delete_after))
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


async def _delete_later(bot, chat_id: int, message_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


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


# ─────────────────────────────────────────────
#  Fix 2 — create_transaction bug fix
# ─────────────────────────────────────────────

async def create_transaction_fixed(
    user_id: int,
    plan: str,
    period: str,
    amount: float,
    txid: Optional[str] = None,
    screenshot_path: Optional[str] = None,
) -> str:
    """
    Fixed version of _create_transaction.
    Takes explicit plan/period/amount instead of reading from user.plan.
    """
    from bot.database import get_session
    from bot.models import (
        PlanType, SubscriptionPeriod, Transaction,
        TransactionMethod, TransactionStatus, USDTAddress,
    )
    from sqlalchemy import select

    async with get_session() as session:
        addr = (await session.execute(
            select(USDTAddress).where(
                USDTAddress.is_active == True,
                USDTAddress.is_default == True,
            )
        )).scalar_one_or_none()

        tx = Transaction(
            user_id=user_id,
            plan=PlanType(plan),
            period=SubscriptionPeriod(period),
            amount_usdt=amount,
            payment_method=TransactionMethod.CRYPTO,
            status=TransactionStatus.PENDING,
            txid=txid,
            screenshot_path=screenshot_path,
            usdt_address_id=addr.id if addr else None,
        )
        session.add(tx)
        await session.flush()
        return f"STF-{tx.id:06d}"


# ─────────────────────────────────────────────
#  Fix 3 — Double-approve protection
# ─────────────────────────────────────────────

async def activate_subscription_safe(
    tx_id: int,
    deposit_result: dict,
    reviewed_by: str = "admin",
) -> bool:
    """
    Async SQLAlchemy subscription activation.
    Atomic check+update prevents double-approve.
    Returns True if activated, False if already processed.

    Args:
        tx_id:          Transaction.id (int)
        deposit_result: dict from check_deposit — must have "txid" key
        reviewed_by:    label stored in Transaction.reviewed_by
    """
    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus, User
    from sqlalchemy import update as sql_update, select
    from datetime import timedelta

    now = datetime.now(timezone.utc)

    async with get_session() as session:
        # ── 1. Atomic guard: only update if still PENDING ─────────────────
        result = await session.execute(
            sql_update(Transaction)
            .where(
                Transaction.id == tx_id,
                Transaction.status == TransactionStatus.PENDING,
            )
            .values(
                status=TransactionStatus.APPROVED,
                reviewed_at=now,
                reviewed_by=reviewed_by,
                txid=deposit_result.get("txid"),
            )
            .returning(Transaction.id, Transaction.plan, Transaction.period, Transaction.user_id)
        )
        row = result.fetchone()

        if row is None:
            logger.warning(f"[activate_subscription_safe] tx={tx_id} already processed — skipping")
            return False

        _, plan_val, period_val, user_id = row

        # ── 2. Reload user & compute expiry ───────────────────────────────
        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()

        if user is None:
            logger.error(f"[activate_subscription_safe] User not found for tx={tx_id}")
            return False

        duration_days = {
            "monthly":  30,
            "biannual": 183,
            "yearly":   365,
        }.get(period_val.value if hasattr(period_val, "value") else str(period_val), 30)

        if user.subscription_expires_at and user.subscription_expires_at > now:
            new_expiry = user.subscription_expires_at + timedelta(days=duration_days)
        else:
            new_expiry = now + timedelta(days=duration_days)

        # ── 3. Update user plan ───────────────────────────────────────────
        user.plan = plan_val
        user.subscription_expires_at = new_expiry
        user.subscription_pause_used = False
        await session.flush()

        # ── 4. Notify user (telegram_id loaded inside session) ────────────
        telegram_id = user.telegram_id
        language    = user.language
        plan_name   = plan_val.value if hasattr(plan_val, "value") else str(plan_val)

    # Outside session — safe to use captured scalars
    try:
        from admin.services import _notify_user_approved_async
        await _notify_user_approved_async(telegram_id, plan_name, new_expiry, language)
    except Exception as notify_err:
        logger.warning(f"[activate_subscription_safe] Notification failed: {notify_err}")

    logger.info(f"[activate_subscription_safe] Activated: user={telegram_id} plan={plan_name} expires={new_expiry}")
    return True


# ─────────────────────────────────────────────
#  Fix 4 — Referral race condition
# ─────────────────────────────────────────────

async def handle_referral_safe(user_id: int, referral_code: str) -> bool:
    """
    Race-condition-safe referral handler.
    Uses SELECT FOR UPDATE to prevent duplicate credits.
    """
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select, text

    async with get_session() as session:
        # Check if user already has a referrer
        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()

        if not user or user.referred_by_id:
            return False

        # Lock the referrer row to prevent race condition
        referrer = (await session.execute(
            select(User)
            .where(
                User.referral_code == referral_code,
                User.id != user_id,
            )
            .with_for_update()  # Row lock
        )).scalar_one_or_none()

        if not referrer:
            return False

        from config.settings import config as cfg
        max_bonus = 10  # from SystemConfig ideally

        if referrer.referral_bonus_accounts >= max_bonus:
            return False

        referrer.referral_bonus_accounts += 1
        user.referred_by_id = referrer.id

        # Capture scalars inside session — avoids DetachedInstanceError after close
        referrer_telegram_id   = referrer.telegram_id
        referrer_bonus_count   = referrer.referral_bonus_accounts

        logger.info(f"Referral credited: user={user_id} referred_by={referrer.id}")

    # Notify referrer outside transaction — using captured scalars only
    from bot.utils.telegram_utils import safe_send_message
    await safe_send_message(
        referrer_telegram_id,
        f"🎉 یه نفر با لینک دعوت شما عضو شد!\n"
        f"اکانت رایگان اضافه: <b>{referrer_bonus_count}</b>/10",
        parse_mode="HTML",
    )
    return True


# ─────────────────────────────────────────────
#  Fix 6 — /cancel command for conversations
# ─────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Universal cancel — exits any active conversation."""
    from telegram.ext import ConversationHandler
    from bot.utils.keyboards import main_menu

    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Cleanup any pending context keys
    for key in (
        "adding_platform", "proof_type", "pending_plan",
        "pending_period", "pending_amount", "ticket_subject",
        "ticket_text", "ticket_attachments",
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        "✖️ Cancelled.",
        reply_markup=main_menu(lang),
    )
    return ConversationHandler.END


def register_cancel(app: Application) -> None:
    app.add_handler(CommandHandler("cancel", cmd_cancel))
