"""
SocialtoFeed — Growth & Re-engagement Tasks
1. Re-engage users who registered but added no accounts (3 days)
2. Upsell when free quota is full
3. Referral viral invite message
4. Download cleanup
5. Rate-limited broadcast
"""

from __future__ import annotations

from config import config
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from worker.tasks import celery_app, _run

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Re-engagement: No accounts after 3 days
# ─────────────────────────────────────────────

@celery_app.task(name="worker.growth.reengage_inactive")
def reengage_inactive_users() -> dict:
    """
    Finds users who registered 3 days ago but never added an account.
    Sends a friendly nudge.
    Runs daily at 11 AM via beat.
    """
    async def _run_task():
        from bot.database import init_db, get_session
        from bot.models import User, Account
        from sqlalchemy import select, func
        from bot.utils.telegram_utils import safe_send_message
        from bot.utils.telegram_utils import get_bot
        from bot.utils.translator import t

        await init_db()
        bot = get_bot()

        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        four_days_ago = datetime.now(timezone.utc) - timedelta(days=4)

        async with get_session() as session:
            # Users registered 3-4 days ago with zero accounts
            users_no_accounts = (await session.execute(
                select(User)
                .where(
                    User.created_at.between(four_days_ago, three_days_ago),
                    User.is_banned == False,
                    ~User.id.in_(
                        select(Account.user_id).distinct()
                    ),
                )
            )).scalars().all()

        sent = 0
        for user in users_no_accounts:
            lang = user.language
            msg = t(
                "growth.reengage_no_accounts",
                lang,
                name=user.first_name or "there",
                default=(
                    f"👋 Hey {user.first_name or 'there'}! Don't forget to add your first account.\n\n"
                    f"Start free with 5 accounts — just paste any link "
                    f"and the bot detects the platform automatically 🎯\n\n"
                    f"👉 /start"
                ),
            )

            result = await safe_send_message(user.telegram_id, msg)
            if result:
                sent += 1
            await asyncio.sleep(0.5)

        logger.info(f"Re-engagement: sent {sent} nudges")
        return {"sent": sent}

    return _run(_run_task())


# ─────────────────────────────────────────────
#  Upsell: Free quota full
# ─────────────────────────────────────────────

from bot.cache import get_redis as _get_upsell_redis  # PERF-4: shared pool


async def send_upsell_if_quota_full(user_id: int, telegram_id: int, lang: str) -> None:
    """
    Called when a free user hits their account limit.
    Sends a compelling upsell message once per 7 days.
    Prices and account counts match aisocialfeed.com exactly.
    """
    from bot.utils.telegram_utils import safe_send_message
    from bot.utils.telegram_utils import get_bot

    cache_key = f"upsell_sent:{user_id}"

    try:
        r = await _get_upsell_redis()
        already_sent = await r.get(cache_key)
        if already_sent:
            return

        bot = get_bot()
        msg = (
            "🔥 <b>به محدودیت رایگان رسیدی!</b>\n\n"
            "با پلن پرو:\n"
            "✅ ۴۰ اکانت (در مقابل ۵ تا)\n"
            "✅ ۱۰ پلتفرم شامل اینستاگرام و لینکدین\n"
            "✅ لینک دانلود ویدیو و صدا\n"
            "✅ خروجی CSV\n\n"
            "💰 فقط <b>۶ دلار</b> در ماه\n\n"
            "👉 /subscription"
        ) if lang == "fa" else (
            "🔥 <b>You've hit the free plan limit!</b>\n\n"
            "Upgrade to <b>Pro</b>:\n"
            "✅ 40 accounts (vs 5 free)\n"
            "✅ 10 platforms incl. Instagram & LinkedIn\n"
            "✅ Video & audio download links\n"
            "✅ CSV export\n\n"
            "💰 Only <b>$6/month</b>\n\n"
            "👉 /subscription"
        )

        await safe_send_message(telegram_id, msg, parse_mode="HTML")

        # Do not send again for 7 days
        await r.setex(cache_key, 60 * 60 * 24 * 7, "1")

    except Exception as e:
        logger.error(f"Upsell send failed: {e}")


# ─────────────────────────────────────────────
#  Referral: Viral invite message
# ─────────────────────────────────────────────

async def send_referral_invite(user, bot_username: str) -> str:
    """
    Generates the referral invite message.
    Returns formatted text — caller sends it.
    """
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select, func
    from bot.models import Account

    async with get_session() as session:
        # Count how many people this user referred
        referred_count = (await session.execute(
            select(func.count()).select_from(User)
            .where(User.referred_by_id == user.id)
        )).scalar() or 0

    lang = user.language
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
    bonus = user.referral_bonus_accounts

    if lang == "fa":
        text = (
            f"🎁 <b>دوستانت رو دعوت کن، اکانت رایگان بگیر!</b>\n\n"
            f"هر دوستی که با لینک تو عضو بشه و حداقل یه اکانت اضافه کنه،\n"
            f"تو <b>۱ اکانت رایگان</b> می‌گیری (تا سقف ۱۰ تا)!\n\n"
            f"🔗 <b>لینک اختصاصی تو:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>وضعیت فعلی:</b>\n"
            f"• دوستان عضو شده: <b>{referred_count}</b>\n"
            f"• اکانت رایگان گرفته: <b>{bonus}</b>/10"
        )
    elif lang == "ar":
        text = (
            f"🎁 <b>ادعُ أصدقاءك واحصل على حسابات مجانية!</b>\n\n"
            f"لكل صديق ينضم عبر رابطك ويضيف حساباً واحداً على الأقل،\n"
            f"ستحصل على <b>حساب مجاني إضافي</b> (بحد أقصى ١٠)!\n\n"
            f"🔗 <b>رابطك الخاص:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>وضعك الحالي:</b>\n"
            f"• الأصدقاء المنضمون: <b>{referred_count}</b>\n"
            f"• الحسابات المجانية: <b>{bonus}</b>/10"
        )
    else:
        text = (
            f"🎁 <b>Invite friends, earn free accounts!</b>\n\n"
            f"For every friend who joins via your link and adds at least one account,\n"
            f"you get <b>1 free account slot</b> (up to 10)!\n\n"
            f"🔗 <b>Your invite link:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>Your stats:</b>\n"
            f"• Friends joined: <b>{referred_count}</b>\n"
            f"• Free accounts earned: <b>{bonus}</b>/10"
        )

    return text


# ─────────────────────────────────────────────
#  Broadcast: Rate-limited (1/sec via Celery)
# ─────────────────────────────────────────────

@celery_app.task(name="worker.growth.broadcast_message")
def broadcast_message_task(message: str, plan_filter: str = "all") -> dict:
    """
    Rate-limited broadcast. 1 message/second.
    Safe from Telegram flood limits.
    """
    async def _broadcast():
        from bot.database import init_db, get_session
        from bot.models import User, PlanType
        from bot.utils.telegram_utils import get_bot, safe_send_message
        from sqlalchemy import select

        await init_db()
        bot = get_bot()

        async with get_session() as session:
            query = select(User.telegram_id).where(User.is_banned == False)
            if plan_filter != "all":
                query = query.where(User.plan == plan_filter)
            tg_ids = (await session.execute(query)).scalars().all()

        sent = failed = 0
        for tg_id in tg_ids:
            result = await safe_send_message(tg_id, message, parse_mode="HTML")
            if result:
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(1.0)  # 1/sec — safe for Telegram

        logger.info(f"Broadcast complete: {sent} sent, {failed} failed")
        return {"sent": sent, "failed": failed, "total": len(tg_ids)}

    return _run(_broadcast())


# ─────────────────────────────────────────────
#  Cleanup: Downloaded video files
# ─────────────────────────────────────────────

@celery_app.task(name="worker.growth.cleanup_downloads")
def cleanup_download_files() -> dict:
    """
    Deletes video files older than 1 hour from /media/downloads.
    Prevents disk fill-up from crashed download tasks.
    """
    from config import config

    download_dir = config.download.output_dir
    if not os.path.exists(download_dir):
        return {"deleted": 0}

    now = datetime.now(timezone.utc).timestamp()
    deleted = 0
    freed_mb = 0.0

    for fname in os.listdir(download_dir):
        fpath = os.path.join(download_dir, fname)
        try:
            if os.path.isfile(fpath):
                age_seconds = now - os.path.getmtime(fpath)
                if age_seconds > 3600:  # older than 1 hour
                    size = os.path.getsize(fpath)
                    os.remove(fpath)
                    deleted += 1
                    freed_mb += size / (1024 * 1024)
        except Exception as e:
            logger.warning(f"Could not delete {fpath}: {e}")

    if deleted:
        logger.info(f"Cleanup: deleted {deleted} files, freed {freed_mb:.1f} MB")

    return {"deleted": deleted, "freed_mb": round(freed_mb, 1)}


# NOTE: Beat schedule for growth tasks (reengage-inactive, cleanup-downloads)
# is defined in worker/tasks.py only. Do not add celery_app.conf.update() here.


@celery_app.task(name="worker.growth.send_share_prompts")
def send_share_prompts() -> dict:
    """
    Send share-bot prompt to eligible users.
    Conditions: first 3 weeks, max 3 times, 1/week.
    """
    async def _send():
        from bot.database import init_db, get_session
        from bot.models import User
        from sqlalchemy import select
        from datetime import datetime, timedelta, timezone
        await init_db()
        now = datetime.now(timezone.utc)
        sent = 0
        async with get_session() as session:
            # Users in first 3 weeks who haven't maxed prompts
            users = (await session.execute(
                select(User).where(
                    User.share_prompt_count < 3,
                    User.created_at >= now - timedelta(days=21),
                    User.is_banned == False,
                )
            )).scalars().all()
        for user in users:
            # Check 7-day interval
            if user.share_prompt_last_at:
                if (now - user.share_prompt_last_at).days < 7:
                    continue
            # Send share prompt via Telegram
            from config import config
            from bot.utils.telegram_utils import safe_send_message
            from bot.handlers.share_bot import _MSGS
            from bot.utils.keyboards import share_bot_keyboard
            lang = user.language
            ref = f"https://t.me/{config.app.bot_username}?start=ref_{user.telegram_id}"
            msg = _MSGS.get(lang, _MSGS["en"])
            try:
                await safe_send_message(
                    user.telegram_id, msg,
                    parse_mode="HTML",
                    reply_markup=share_bot_keyboard(lang, ref),
                )
                # Update counter
                async with get_session() as session:
                    from sqlalchemy import select
                    db_u = (await session.execute(
                        select(User).where(User.id == user.id)
                    )).scalar_one_or_none()
                    if db_u:
                        db_u.share_prompt_count = (db_u.share_prompt_count or 0) + 1
                        db_u.share_prompt_last_at = now
                sent += 1
            except Exception as e:
                logger.debug(f"Share prompt failed user {user.telegram_id}: {e}")
        return {"sent": sent}

    return _run(_send())

