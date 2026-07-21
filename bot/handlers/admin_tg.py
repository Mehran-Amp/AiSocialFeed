"""
SocialtoFeed — Telegram Admin Panel
All admin operations via inline keyboard buttons.
Only accessible to ADMIN_TELEGRAM_ID.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middlewares.auth import require_admin
from bot.utils.keyboards import (
    admin_broadcast_targets,
    admin_confirm,
    admin_grant_plan,
    admin_main_menu,
    admin_user_actions,
)
from bot.utils.telegram_utils import safe_send_message
from config import config

logger = logging.getLogger(__name__)

# ConversationHandler states
_BROADCAST_TEXT = 1
_SEARCH_USER    = 2


# ─────────────────────────────────────────────────────────────────────────────
#  Entry Points
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin command — opens admin menu."""
    await show_admin_menu(update, context)


@require_admin
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main admin menu with inline buttons."""
    text = (
        "⚙️ <b>Admin Panel</b>\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_main_menu())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_main_menu())


# ─────────────────────────────────────────────────────────────────────────────
#  Stats
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import User, Transaction, TransactionStatus, Account
    from sqlalchemy import select, func

    async with get_session() as session:
        total_users   = (await session.execute(select(func.count(User.id)))).scalar()
        active_subs   = (await session.execute(
            select(func.count(User.id)).where(
                User.subscription_expires_at > datetime.now(timezone.utc)
            )
        )).scalar()
        total_accounts = (await session.execute(select(func.count(Account.id)))).scalar()

        since_30d = datetime.now(timezone.utc) - timedelta(days=30)
        revenue_30d = (await session.execute(
            select(func.sum(Transaction.amount_usdt)).where(
                Transaction.status == TransactionStatus.APPROVED,
                Transaction.created_at >= since_30d,
            )
        )).scalar() or 0.0

        pending_txs = (await session.execute(
            select(func.count(Transaction.id)).where(
                Transaction.status == TransactionStatus.PENDING,
            )
        )).scalar()

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])

    text = (
        "📊 <b>Live Stats</b>\n\n"
        f"👥 Total Users:       <b>{total_users:,}</b>\n"
        f"✅ Active Subs:       <b>{active_subs:,}</b>\n"
        f"📱 Total Accounts:    <b>{total_accounts:,}</b>\n"
        f"💰 Revenue (30d):     <b>${revenue_30d:.2f}</b>\n"
        f"⏳ Pending Payments:  <b>{pending_txs}</b>\n"
        f"\n🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


# ─────────────────────────────────────────────────────────────────────────────
#  Revenue
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus
    from sqlalchemy import select, func

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        def _rev(days):
            since = now - timedelta(days=days)
            return session.execute(
                select(func.sum(Transaction.amount_usdt)).where(
                    Transaction.status == TransactionStatus.APPROVED,
                    Transaction.created_at >= since,
                )
            )
        r7, r30, r90 = (
            (await _rev(7)).scalar() or 0.0,
            (await _rev(30)).scalar() or 0.0,
            (await _rev(90)).scalar() or 0.0,
        )
        # MRR approximation: last 30 days
        mrr = r30

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])

    text = (
        "💰 <b>Revenue Report</b>\n\n"
        f"📅 Last 7 days:   <b>${r7:.2f}</b>\n"
        f"📅 Last 30 days:  <b>${r30:.2f}</b>\n"
        f"📅 Last 90 days:  <b>${r90:.2f}</b>\n\n"
        f"📈 MRR (est.):    <b>${mrr:.2f}</b>\n"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


# ─────────────────────────────────────────────────────────────────────────────
#  Transactions — stuck/pending
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus, TransactionMethod
    from sqlalchemy import select

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with get_session() as session:
        stuck = (await session.execute(
            select(Transaction).where(
                Transaction.status == TransactionStatus.PENDING,
                Transaction.payment_method == TransactionMethod.CRYPTO,
                Transaction.created_at <= cutoff,
            ).order_by(Transaction.created_at).limit(10)
        )).scalars().all()

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not stuck:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])
        await query.edit_message_text("✅ No stuck transactions.", reply_markup=kb)
        return

    lines = ["⏳ <b>Stuck Transactions (&gt;30 min)</b>\n"]
    buttons = []
    for tx in stuck:
        age = int((datetime.now(timezone.utc) - tx.created_at).total_seconds() // 60)
        lines.append(f"• <code>#{tx.id}</code> — ${tx.amount_usdt:.2f} — {age}m ago")
        buttons.append([
            InlineKeyboardButton(f"🔄 Retry #{tx.id}", callback_data=f"adm:retry:{tx.id}"),
        ])

    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@require_admin
async def cb_retry_tx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    tx_id = int(query.data.split(":")[2])

    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus
    from bot.services.payment_service import check_deposit
    from bot.utils.fixes import activate_subscription_safe
    from sqlalchemy import select

    async with get_session() as session:
        tx = (await session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )).scalar_one_or_none()

    if not tx:
        await query.answer("Transaction not found.", show_alert=True)
        return

    result = await check_deposit(
        tx.deposit_address,
        tx.network,
        float(tx.amount_usdt),
        tx.address_generated_at or tx.created_at,
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:txs")]])

    if result and result.get("confirmed") and result.get("enough"):
        activated = await activate_subscription_safe(
            tx_id=tx.id,
            deposit_result=result,
            reviewed_by="admin:manual_retry",
        )
        msg = f"✅ TX #{tx_id} activated." if activated else f"ℹ️ TX #{tx_id} already processed."
    else:
        msg = f"⚠️ TX #{tx_id} — deposit not confirmed yet."

    await query.edit_message_text(msg, reply_markup=back_kb)


# ─────────────────────────────────────────────────────────────────────────────
#  Users — search + actions
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search by ID or username", callback_data="adm:usersearch")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")],
    ])
    await query.edit_message_text(
        "👥 <b>Users</b>\nChoose an action:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@require_admin
async def cb_user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 Send user's Telegram ID or @username:")
    return _SEARCH_USER


async def cb_user_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from config import config as cfg
    if update.effective_user.id != cfg.telegram.admin_id:
        return _SEARCH_USER

    term = update.message.text.strip().lstrip("@")

    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select, or_

    async with get_session() as session:
        try:
            tg_id = int(term)
            user = (await session.execute(
                select(User).where(User.telegram_id == tg_id)
            )).scalar_one_or_none()
        except ValueError:
            user = (await session.execute(
                select(User).where(User.username.ilike(f"%{term}%"))
            )).scalar_one_or_none()

        if not user:
            await update.message.reply_text("❌ User not found.")
            return _SEARCH_USER

        uid        = user.id
        tg_id      = user.telegram_id
        username   = user.username or "—"
        plan       = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        expires    = user.subscription_expires_at.strftime("%Y-%m-%d") if user.subscription_expires_at else "—"
        is_banned  = getattr(user, "is_banned", False)
        lang       = user.language

    text = (
        f"👤 <b>User Detail</b>\n\n"
        f"ID:       <code>{uid}</code>\n"
        f"TG ID:    <code>{tg_id}</code>\n"
        f"Username: @{username}\n"
        f"Plan:     <b>{plan}</b>\n"
        f"Expires:  {expires}\n"
        f"Lang:     {lang}\n"
        f"Banned:   {'🚫 Yes' if is_banned else '✅ No'}\n"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_user_actions(uid, is_banned),
    )
    return -1  # end conversation


@require_admin
async def cb_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])

    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if not user:
            await query.answer("User not found.", show_alert=True)
            return
        plan      = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        expires   = user.subscription_expires_at.strftime("%Y-%m-%d") if user.subscription_expires_at else "—"
        is_banned = getattr(user, "is_banned", False)
        tg_id     = user.telegram_id
        username  = user.username or "—"
        lang      = user.language

    text = (
        f"👤 <b>User Detail</b>\n\n"
        f"ID:       <code>{uid}</code>\n"
        f"TG ID:    <code>{tg_id}</code>\n"
        f"Username: @{username}\n"
        f"Plan:     <b>{plan}</b>\n"
        f"Expires:  {expires}\n"
        f"Lang:     {lang}\n"
        f"Banned:   {'🚫 Yes' if is_banned else '✅ No'}\n"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_user_actions(uid, is_banned))


@require_admin
async def cb_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])
    await query.edit_message_reply_markup(reply_markup=admin_confirm(f"ban:{uid}", "Ban"))


@require_admin
async def cb_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])
    await query.edit_message_reply_markup(reply_markup=admin_confirm(f"unban:{uid}", "Unban"))


@require_admin
async def cb_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])
    await query.edit_message_reply_markup(reply_markup=admin_grant_plan(uid))


@require_admin
async def cb_grant_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """adm:grantplan:<uid>:<plan>:<days>"""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    uid, plan_str, days = int(parts[2]), parts[3], int(parts[4])

    from bot.database import get_session
    from bot.models import User, PlanType
    from sqlalchemy import select

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if not user:
            await query.answer("User not found.", show_alert=True)
            return
        try:
            user.plan = PlanType(plan_str)
        except ValueError:
            user.plan = PlanType.FREE
        if days > 0:
            now = datetime.now(timezone.utc)
            base = user.subscription_expires_at if (user.subscription_expires_at and user.subscription_expires_at > now) else now
            user.subscription_expires_at = base + timedelta(days=days)
        else:
            user.subscription_expires_at = None
        tg_id = user.telegram_id

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"adm:userdetail:{uid}")]])
    msg = f"✅ Granted <b>{plan_str}</b> for <b>{days}d</b> to user <code>{uid}</code>"
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=back_kb)

    # Notify user
    try:
        await safe_send_message(tg_id, f"🎁 Your plan has been updated to <b>{plan_str}</b> for {days} days!", parse_mode="HTML")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Confirm / Cancel
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generic confirm handler — adm:confirm:<action>:<id>"""
    query = update.callback_query
    await query.answer()
    # data: adm:confirm:ban:123  or  adm:confirm:unban:123
    parts  = query.data.split(":")   # ['adm','confirm','ban','123']
    action = parts[2]
    uid    = int(parts[3])

    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if not user:
            await query.answer("User not found.", show_alert=True)
            return
        tg_id = user.telegram_id
        if action == "ban":
            user.is_banned = True
            msg = f"🚫 User <code>{uid}</code> has been banned."
            notify = "⛔️ Your account has been suspended."
        else:
            user.is_banned = False
            msg = f"✅ User <code>{uid}</code> has been unbanned."
            notify = "✅ Your account has been reinstated."

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:users")]])
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=back_kb)
    try:
        await safe_send_message(tg_id, notify)
    except Exception:
        pass


@require_admin
async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Cancelled.")
    await show_admin_menu(update, context)


# ─────────────────────────────────────────────────────────────────────────────
#  Broadcast
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 <b>Broadcast</b>\n\nSend the message text to broadcast:",
        parse_mode=ParseMode.HTML,
    )
    return _BROADCAST_TEXT


async def bc_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from config import config as cfg
    if update.effective_user.id != cfg.telegram.admin_id:
        return _BROADCAST_TEXT
    context.user_data["bc_text"] = update.message.text
    await update.message.reply_text(
        f"📋 Message:\n<i>{update.message.text}</i>\n\nChoose target:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_broadcast_targets(),
    )
    return -1  # end conversation — target selected via callback


@require_admin
async def cb_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """adm:bc:<target>  — target: all | pro | premium | cancel"""
    query = update.callback_query
    await query.answer()
    target = query.data.split(":")[2]

    if target == "cancel":
        await show_admin_menu(update, context)
        return

    text = context.user_data.get("bc_text")
    if not text:
        await query.edit_message_text("❌ No message text found. Start over.")
        return

    from bot.database import get_session
    from bot.models import User, PlanType
    from sqlalchemy import select
    import asyncio

    await query.edit_message_text("⏳ Broadcast in progress…")

    # SCALE-1 fix: stream IDs in batches of 500 instead of loading all into memory.
    # Send with a semaphore of 25 concurrent requests to stay well under
    # Telegram's ~30 msg/s global rate limit.
    semaphore = asyncio.Semaphore(25)
    sent = failed = 0

    async def send_one(tg_id: int) -> None:
        nonlocal sent, failed
        async with semaphore:
            try:
                await safe_send_message(tg_id, text, parse_mode="HTML")
                sent += 1
            except Exception:
                failed += 1

    async with get_session() as session:
        q = select(User.telegram_id).where(User.is_banned == False)
        if target == "pro":
            q = q.where(User.plan == PlanType.PRO)
        elif target == "premium":
            q = q.where(User.plan == PlanType.PREMIUM)

        stream = await session.stream(q.execution_options(yield_per=500))
        async for partition in stream.scalars().partitions(500):
            await asyncio.gather(*[send_one(tid) for tid in partition])

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])
    await query.edit_message_text(
        f"📢 Broadcast done.\n✅ Sent: <b>{sent}</b>  ❌ Failed: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  System Status
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from worker.tasks import celery_app
    from bot.database import get_session
    from bot.models import Account
    from sqlalchemy import select, func

    # Celery workers
    try:
        inspect   = celery_app.control.inspect(timeout=2)
        active    = inspect.active() or {}
        workers   = list(active.keys())
        wline     = f"✅ {len(workers)} worker(s) online" if workers else "❌ No workers online"
    except Exception:
        wline = "⚠️ Cannot reach workers"

    # Platform error rates via Account.last_error field
    try:
        from bot.database import get_session as _gs
        from bot.models import Account
        from sqlalchemy import select, func, case
        async with _gs() as session:
            rows = (await session.execute(
                select(
                    Account.platform,
                    func.count(Account.id).label("total"),
                    func.sum(
                        case((Account.last_error.isnot(None), 1), else_=0)
                    ).label("errors"),
                ).where(Account.is_active == True)
                .group_by(Account.platform)
                .order_by(func.sum(
                    case((Account.last_error.isnot(None), 1), else_=0)
                ).desc())
                .limit(6)
            )).fetchall()
        plines = []
        for r in rows:
            total = r.total or 1
            pct   = int((r.errors or 0) / total * 100)
            icon  = "🔴" if pct > 50 else ("🟡" if pct > 20 else "🟢")
            pname = r.platform.value if hasattr(r.platform, "value") else str(r.platform)
            plines.append(f"  {icon} {pname}: {pct}% errors ({r.total} accts)")
        platform_text = "\n".join(plines) if plines else "  ✅ All platforms OK"
    except Exception as _pe:
        platform_text = f"  ⚠️ Could not load platform data"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])

    text = (
        "🖥 <b>System Status</b>\n\n"
        f"🔧 Workers:\n  {wline}\n\n"
        f"📡 Platforms (last 1h):\n{platform_text}\n\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


# ─────────────────────────────────────────────────────────────────────────────
#  Anomaly Alerts
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    alerts = await _collect_anomalies()

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:menu")]])

    if not alerts:
        await query.edit_message_text("✅ No active anomalies.", reply_markup=back_kb)
        return

    text = "🚨 <b>Active Alerts</b>\n\n" + "\n".join(f"• {a}" for a in alerts)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


async def _collect_anomalies() -> list[str]:
    """Collect current anomalies — called by alerts button and Celery beat."""
    alerts = []

    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus, TransactionMethod
    from sqlalchemy import select, func

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with get_session() as session:
        stuck_count = (await session.execute(
            select(func.count(Transaction.id)).where(
                Transaction.status == TransactionStatus.PENDING,
                Transaction.payment_method == TransactionMethod.CRYPTO,
                Transaction.created_at <= cutoff,
            )
        )).scalar()
        if stuck_count:
            alerts.append(f"⏳ {stuck_count} payment(s) stuck >30 min")

    # Worker check
    try:
        from worker.tasks import celery_app
        inspect = celery_app.control.inspect(timeout=2)
        active  = inspect.active() or {}
        if not active:
            alerts.append("❌ No Celery workers online")
    except Exception:
        alerts.append("⚠️ Cannot reach Celery broker")

    return alerts


async def check_anomalies_and_notify(bot) -> None:
    """Called by Celery beat every 5 min — pushes alerts to admin if any."""
    alerts = await _collect_anomalies()
    if not alerts:
        return
    text = "🚨 <b>Anomaly Alert</b>\n\n" + "\n".join(f"• {a}" for a in alerts)
    try:
        await safe_send_message(config.telegram.admin_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[check_anomalies] Failed to notify admin: {e}")


async def cb_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    v3.2: Debug panel — real-time snapshot of all critical system states.
    Circuit breakers, last errors, queue depth, pending payments, webhook health.
    """
    query = update.callback_query
    await query.answer()

    now = datetime.now(timezone.utc)
    lines = ["🔍 <b>Debug Panel</b>\n━━━━━━━━━━━━━━━━━━━━"]

    # ── Circuit Breakers ──────────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()
        cb_open  = [k.split(":")[-1] for k in (await r.keys("cb:open:*"))]
        cb_half  = [k.split(":")[-1] for k in (await r.keys("cb:half_open:*"))]
        from bot.models import Platform
        all_platforms = [p.value for p in Platform]
        cb_lines = []
        for p in all_platforms:
            if p in cb_open:   cb_lines.append(f"  🔴 {p} OPEN")
            elif p in cb_half: cb_lines.append(f"  🟡 {p} HALF-OPEN")
        if not cb_lines:
            lines.append("🔌 <b>Circuits:</b> 🟢 All closed")
        else:
            lines.append("🔌 <b>Circuits:</b>\n" + "\n".join(cb_lines))
    except Exception as e:
        lines.append(f"🔌 <b>Circuits:</b> ⚠️ {e}")

    # ── Last 5 errors ─────────────────────────────────────────────────────────
    try:
        from bot.database import get_session
        from bot.models import SystemLog, LogLevel
        from sqlalchemy import select
        async with get_session() as session:
            recent = (await session.execute(
                select(SystemLog)
                .where(SystemLog.level.in_([LogLevel.ERROR, LogLevel.CRITICAL]))
                .order_by(SystemLog.created_at.desc())
                .limit(5)
            )).scalars().all()
        if recent:
            err_lines = "\n".join(
                f"  • {e.created_at.strftime('%H:%M')} {e.message[:50]}…"
                for e in recent
            )
            lines.append(f"❌ <b>Last 5 errors:</b>\n{err_lines}")
        else:
            lines.append("❌ <b>Last 5 errors:</b> ✅ None")
    except Exception as e:
        lines.append(f"❌ <b>Errors:</b> ⚠️ {e}")

    # ── Celery queue + workers ────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()
        queue_depth  = await r.llen("celery") or 0
        hb_keys      = await r.keys("celery:worker:heartbeat:*")
        worker_count = len(hb_keys)

        # Pending payment monitors
        pm_key  = "payment:monitors"
        pm_count= await r.hlen(pm_key) or 0

        lines.append(
            f"⚙️ <b>Queue:</b> {queue_depth} tasks\n"
            f"⚙️ <b>Workers:</b> {worker_count} alive\n"
            f"💳 <b>Payment monitors:</b> {pm_count} active"
        )
    except Exception as e:
        lines.append(f"⚙️ <b>Queue/Workers:</b> ⚠️ {e}")

    # ── Webhook health ────────────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()
        wh_key = now.strftime("webhook:success:%Y%m%d%H")
        wh_count = int(await r.get(wh_key) or 0)
        prev_key = (now.replace(minute=0, second=0, microsecond=0)
                    - timedelta(hours=1)).strftime("webhook:success:%Y%m%d%H")
        prev_count = int(await r.get(prev_key) or 0)
        status = "🟢" if wh_count > 0 else "🔴"
        lines.append(
            f"📡 <b>Webhook:</b> {status} "
            f"{wh_count} updates this hour / {prev_count} last hour"
        )
    except Exception as e:
        lines.append(f"📡 <b>Webhook:</b> ⚠️ {e}")

    # ── Redis memory ──────────────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()
        info = await r.info("memory")
        mem_mb = round(info.get("used_memory", 0) / 1024 / 1024, 1)
        peak_mb = round(info.get("used_memory_peak", 0) / 1024 / 1024, 1)
        lines.append(f"🗄 <b>Redis:</b> {mem_mb} MB used / {peak_mb} MB peak")
    except Exception as e:
        lines.append(f"🗄 <b>Redis:</b> ⚠️ {e}")

    lines.append(f"\n🕐 {now.strftime('%Y-%m-%d %H:%M UTC')}")

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="adm:debug"),
         InlineKeyboardButton("⬅️ Back",    callback_data="adm:menu")],
    ])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Register
# ─────────────────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    # /admin command
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Main menu callbacks
    app.add_handler(CallbackQueryHandler(show_admin_menu,     pattern=r"^adm:menu$"))
    app.add_handler(CallbackQueryHandler(cb_stats,            pattern=r"^adm:stats$"))
    app.add_handler(CallbackQueryHandler(cb_revenue,          pattern=r"^adm:revenue$"))
    app.add_handler(CallbackQueryHandler(cb_transactions,     pattern=r"^adm:txs$"))
    app.add_handler(CallbackQueryHandler(cb_users,            pattern=r"^adm:users$"))
    app.add_handler(CallbackQueryHandler(cb_system,           pattern=r"^adm:system$"))
    app.add_handler(CallbackQueryHandler(cb_alerts,           pattern=r"^adm:alerts$"))
    app.add_handler(CallbackQueryHandler(cb_debug,            pattern=r"^adm:debug$"))  # v3.2
    # User actions
    app.add_handler(CallbackQueryHandler(cb_user_detail,      pattern=r"^adm:userdetail:"))
    app.add_handler(CallbackQueryHandler(cb_ban,              pattern=r"^adm:ban:"))
    app.add_handler(CallbackQueryHandler(cb_unban,            pattern=r"^adm:unban:"))
    app.add_handler(CallbackQueryHandler(cb_grant,            pattern=r"^adm:grant:"))
    app.add_handler(CallbackQueryHandler(cb_grant_plan,       pattern=r"^adm:grantplan:"))
    app.add_handler(CallbackQueryHandler(cb_confirm,          pattern=r"^adm:confirm:"))
    app.add_handler(CallbackQueryHandler(cb_cancel,           pattern=r"^adm:cancel$"))

    # Transaction actions
    app.add_handler(CallbackQueryHandler(cb_retry_tx,         pattern=r"^adm:retry:"))

    # Broadcast send
    app.add_handler(CallbackQueryHandler(cb_broadcast_send,   pattern=r"^adm:bc:"))

    # Conversation: user search
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_user_search_start, pattern=r"^adm:usersearch$")],
        states={_SEARCH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, cb_user_search_receive)]},
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    ))

    # Conversation: broadcast text input
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_broadcast, pattern=r"^adm:broadcast$")],
        states={_BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bc_receive_text)]},
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    ))

    logger.info("Admin Telegram handlers registered.")
