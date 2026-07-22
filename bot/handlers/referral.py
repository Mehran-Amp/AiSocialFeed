"""SocialtoFeed — Referral Handler v4.2 — progress bar, history, milestones"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from bot.database import get_session
from bot.models import PlanType, User
from bot.utils.keyboards import (
    referral_menu,
    referral_share_keyboard,
    referral_rewards_keyboard,
    back_button,
)
from bot.utils.telegram_utils import safe_send_message

logger = logging.getLogger(__name__)

MILESTONE_POINTS = 10  # bonus points at every 5-referral milestone
POINTS_PER_REF = 2
NEW_USER_BONUS = 1
MAX_BONUS_ACCTS = 10


def _progress_bar(current: int, target: int, width: int = 10) -> str:
    filled = int(width * min(current, target) / target) if target else 0
    return "█" * filled + "░" * (width - filled)


def _get_referral_stats(count: int) -> tuple[int, str, int]:
    next_ms = ((count // 5) + 1) * 5
    bar = _progress_bar(count % 5, 5)
    remaining = next_ms - count
    return next_ms, bar, remaining


def _build_referral_menu_text(
    fa: bool, count: int, points: int, bar: str, remaining: int
) -> str:
    if fa:
        return (
            f"📤 <b>دعوت از دوستان</b>\n\n"
            f"👥 دعوت‌شده‌ها: <b>{count}</b>\n"
            f"⭐️ امتیاز: <b>{points}</b>\n\n"
            f"پیشرفت به جایزه بعدی:\n"
            f"{bar} {count%5}/5\n"
            f"({remaining} نفر تا جایزه بعدی)"
        )
    return (
        f"📤 <b>Refer & Earn</b>\n\n"
        f"👥 Referred: <b>{count}</b>\n"
        f"⭐️ Points: <b>{points}</b>\n\n"
        f"Progress to next reward:\n"
        f"{bar} {count%5}/5\n"
        f"({remaining} more to next milestone)"
    )


async def show_referral(update, context, user):
    """
    Top-level Referral screen (per spec): Share / Rewards / History / Back-to-profile.
    Issue 3 fix: this used to render the share screen, causing Back to loop.
    """
    lang = user.language
    fa = lang == "fa"
    points = user.referral_points or 0
    count = user.referral_count or 0
    next_ms, bar, remaining = _get_referral_stats(count)

    txt = _build_referral_menu_text(fa, count, points, bar, remaining)

    kb = referral_menu(lang, points, next_ms)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                txt, parse_mode=ParseMode.HTML, reply_markup=kb
            )
            return
        except Exception:
            pass
    await safe_send_message(
        update.effective_user.id, txt, parse_mode=ParseMode.HTML, reply_markup=kb
    )


async def show_referral_share(query, context, user):
    """The actual Share Link screen — Share / Copy Link / Back-to-referral-menu."""
    lang = user.language
    fa = lang == "fa"
    bot_username = context.bot.username or "AiSocialFeedBot"
    ref_code = user.referral_code or ""
    ref_link = f"https://t.me/{bot_username}?start=ref_{ref_code}"
    points = user.referral_points or 0

    if fa:
        txt = (
            f"📤 <b>اشتراک‌گذاری لینک</b>\n\n"
            f"🔗 لینک شما:\n<code>{ref_link}</code>\n\n"
            f"روی لینک بالا بزن و نگه‌دار تا کپی شود، یا از دکمه اشتراک‌گذاری استفاده کن."
        )
    else:
        txt = (
            f"📤 <b>Share Your Link</b>\n\n"
            f"🔗 Your link:\n<code>{ref_link}</code>\n\n"
            f"Tap-and-hold the link above to copy it, or use the Share button."
        )

    kb = referral_share_keyboard(lang, ref_link, points)
    await query.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_referral_rewards(query, user):
    lang = user.language
    fa = lang == "fa"
    points = user.referral_points or 0
    t1 = "جوایز شما" if fa else "Your Rewards"
    txt = f"🎁 <b>{t1}</b>\n\n⭐️ {'امتیاز' if fa else 'Points'}: <b>{points}</b>\n"
    await query.edit_message_text(
        txt,
        parse_mode=ParseMode.HTML,
        reply_markup=referral_rewards_keyboard(lang, points),
    )


async def show_referral_history(query, user):
    lang = user.language
    fa = lang == "fa"
    try:
        async with get_session() as s:
            from sqlalchemy import select

            referred = (
                (
                    await s.execute(
                        select(User)
                        .where(User.referred_by_id == user.id)
                        .order_by(User.created_at.desc())
                        .limit(10)
                    )
                )
                .scalars()
                .all()
            )
        if not referred:
            t1 = "هنوز کسی رو دعوت نکردی." if fa else "No referrals yet."
            txt = f"📋 {t1}"
        else:
            rows = "\n".join(
                f"• @{u.username or u.telegram_id} — {u.created_at.strftime('%Y-%m-%d') if u.created_at else '?'}"
                for u in referred
            )
            t1 = "تاریخچه رفرال" if fa else "Referral History"
            txt = f"📋 <b>{t1}</b>\n\n{rows}"
    except Exception:
        txt = "📋 Could not load history."
    await query.edit_message_text(
        txt, parse_mode=ParseMode.HTML, reply_markup=back_button(lang, "referral:menu")
    )


async def handle_redeem(query, user, pts_cost, reward):
    lang = user.language
    fa = lang == "fa"
    if (user.referral_points or 0) < pts_cost:
        t1 = "امتیاز کافی ندارید." if fa else "Not enough points."
        await query.answer(t1, show_alert=True)
        return
    async with get_session() as s:
        from sqlalchemy import select
        from bot.models import User as U

        db = (await s.execute(select(U).where(U.id == user.id))).scalar_one_or_none()
        if not db:
            return
        db.referral_points = (db.referral_points or 0) - pts_cost
        user.referral_points = db.referral_points
        if reward == "pro_week":
            _extend(db, "pro", 7)
        elif reward == "pro_month":
            _extend(db, "pro", 30)
        elif reward == "premium_month":
            _extend(db, "premium", 30)
        elif reward == "premium_3month":
            _extend(db, "premium", 90)
        user.plan = db.plan
        user.subscription_expires_at = db.subscription_expires_at
    t1 = "استفاده شد! جایزه اعمال گردید." if fa else "Redeemed! Reward applied."
    await query.answer(t1, show_alert=True)
    await show_referral_rewards(query, user)


def _extend(db, plan_str, days):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    base = (
        db.subscription_expires_at
        if (db.subscription_expires_at and db.subscription_expires_at > now)
        else now
    )
    db.plan = plan_str
    db.subscription_expires_at = base + timedelta(days=days)


async def handle_referral_safe(new_user_id, referrer_code):
    try:
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import User as U

            referrer = (
                await s.execute(select(U).where(U.referral_code == referrer_code))
            ).scalar_one_or_none()
            new_user = (
                await s.execute(select(U).where(U.id == new_user_id))
            ).scalar_one_or_none()
            if not referrer or not new_user:
                return False
            if referrer.id == new_user.id or new_user.referred_by_id:
                return False
            new_user.referred_by_id = referrer.id
            referrer.referral_count = (referrer.referral_count or 0) + 1
            referrer.referral_points = (referrer.referral_points or 0) + POINTS_PER_REF
            if (referrer.referral_bonus_accounts or 0) < MAX_BONUS_ACCTS:
                referrer.referral_bonus_accounts = min(
                    (referrer.referral_bonus_accounts or 0) + 1, MAX_BONUS_ACCTS
                )
            new_user.referral_points = (new_user.referral_points or 0) + NEW_USER_BONUS
            # Milestone bonus every 5 referrals
            milestones_earned = (referrer.referral_count or 0) // 5
            if milestones_earned > (referrer.referral_milestones_claimed or 0):
                referrer.referral_points += MILESTONE_POINTS
                referrer.referral_milestones_claimed = milestones_earned
        from bot.utils.telegram_utils import safe_send_message

        lang = referrer.language or "en"
        fa = lang == "fa"
        count = referrer.referral_count or 0
        t1 = (
            f"🎉 یک امتیاز رفرال کسب کردید! جمع: {count}"
            if fa
            else f"🎉 You earned a referral point! Total: {count}"
        )
        await safe_send_message(referrer.telegram_id, t1)
        return True
    except Exception as e:
        logger.error(f"[referral] handle_referral_safe: {e}")
        return False


async def cb_referral(update, context):
    query = update.callback_query
    user = context.user_data.get("user")
    if not user:
        await query.answer()
        return
    action = query.data.split(":")[1] if ":" in query.data else ""
    if action == "menu":
        await query.answer()
        await show_referral(update, context, user)
    elif action == "share":
        await query.answer()
        await show_referral_share(query, context, user)
    elif action == "rewards":
        await query.answer()
        await show_referral_rewards(query, user)
    elif action == "history":
        await query.answer()
        await show_referral_history(query, user)
    elif action == "need_more":
        lang = user.language
        fa = lang == "fa"
        await query.answer(
            "امتیاز کافی ندارید." if fa else "Not enough points yet.", show_alert=True
        )
    elif action == "redeem" and len(query.data.split(":")) >= 4:
        await query.answer()
        parts = query.data.split(":")
        await handle_redeem(query, user, int(parts[2]), parts[3])
    elif action == "copy":
        # Issue 2 fix: alert popups aren't copyable in most Telegram clients.
        # Send a real message with the link in a <code> block instead —
        # Telegram natively shows a tap-to-copy affordance on code blocks.
        lang = user.language
        fa = lang == "fa"
        bot_username = context.bot.username or "AiSocialFeedBot"
        ref_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code or ''}"
        t1 = (
            "لینک شما (برای کپی روی آن نگه دارید):"
            if fa
            else "Your link (tap-and-hold to copy):"
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"📋 {t1}\n\n<code>{ref_link}</code>",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("✅ " + ("لینک ارسال شد" if fa else "Link sent"))
    else:
        await query.answer()
