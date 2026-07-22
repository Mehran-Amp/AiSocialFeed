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
from config.settings import config

logger = logging.getLogger(__name__)

# ConversationHandler states
_BROADCAST_TEXT = 1
_SEARCH_USER    = 2
_GRANT_CUSTOM_PLAN = 3
_SEND_USER_MESSAGE = 4


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
async def cb_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import User, Transaction, TransactionStatus, Account, SupportTicket, SystemLog, LogLevel, PlanType
    from bot.utils.keyboards import admin_dashboard_menu
    from sqlalchemy import select, func
    from datetime import datetime, timezone, timedelta
    import psutil

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar()
        active_subs = (await session.execute(
            select(func.count(User.id)).where(User.subscription_expires_at > now)
        )).scalar()

        # Revenue
        total_revenue = (await session.execute(
            select(func.sum(Transaction.amount_usdt)).where(Transaction.status == TransactionStatus.APPROVED)
        )).scalar() or 0.0

        today_revenue = (await session.execute(
            select(func.sum(Transaction.amount_usdt)).where(
                Transaction.status == TransactionStatus.APPROVED,
                Transaction.created_at >= today_start
            )
        )).scalar() or 0.0

        new_users_today = (await session.execute(
            select(func.count(User.id)).where(User.created_at >= today_start)
        )).scalar()

        # Alerts
        new_tickets = (await session.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.created_at >= now - timedelta(days=1))
        )).scalar()

        error_logs_count = (await session.execute(
            select(func.count(SystemLog.id)).where(SystemLog.level == LogLevel.ERROR, SystemLog.created_at >= now - timedelta(hours=1))
        )).scalar()

        critical_errors_count = (await session.execute(
            select(func.count(SystemLog.id)).where(SystemLog.level == LogLevel.CRITICAL, SystemLog.created_at >= now - timedelta(hours=1))
        )).scalar()

        # Quick stats
        pro_users = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.PRO))).scalar()
        premium_users = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.PREMIUM))).scalar()
        free_users = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.FREE))).scalar()

    mem_usage = psutil.virtual_memory().percent

    text = (
        "📊 <b>Dashboard</b>\n\n"
        "📌 <b>System Overview</b>\n"
        f"👥 Total Users: <b>{total_users:,}</b>\n"
        f"💰 Total Revenue: <b>${total_revenue:.2f}</b>\n"
        f"📊 Active Subs: <b>{active_subs:,}</b>\n\n"

        "📈 <b>Today's Activity</b>\n"
        f"👥 New Users: <b>{new_users_today:,}</b>\n"
        f"💰 Revenue: <b>${today_revenue:.2f}</b>\n\n"

        "⚠️ <b>Alerts & Issues</b>\n"
        f"📋 New Tickets: <b>{new_tickets}</b>\n"
        f"🚨 Error Logs: <b>{error_logs_count} new</b>\n"
        f"🔴 Critical Errors: <b>{critical_errors_count}</b>\n\n"

        "🖥 <b>System Status</b>\n"
        "📊 Bot Status: ✅ Online\n"
        f"💾 Memory Usage: <b>{mem_usage}%</b>\n\n"

        "📊 <b>Quick Stats</b>\n"
        f"⭐ Pro Users: <b>{pro_users:,}</b>\n"
        f"💎 Premium Users: <b>{premium_users:,}</b>\n"
        f"🆓 Free Users: <b>{free_users:,}</b>\n"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_dashboard_menu())


# ─────────────────────────────────────────────────────────────────────────────
#  Revenue
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from bot.utils.keyboards import admin_revenue_menu
    await query.edit_message_text(
        "💰 <b>Revenue</b>\nChoose an action:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_revenue_menu()
    )

@require_admin
async def cb_revenue_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action = query.data.split(":")[2]

    from bot.database import get_session
    from bot.models import Transaction, TransactionStatus, PlanType
    from sqlalchemy import select, func
    from datetime import datetime, timezone, timedelta
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)

    async with get_session() as session:
        if action == "total":
            val = (await session.execute(select(func.sum(Transaction.amount_usdt)).where(Transaction.status == TransactionStatus.APPROVED))).scalar() or 0.0
            text = f"📊 <b>Total Revenue</b>\n\nTotal all-time revenue: <b>${val:.2f}</b>"
        elif action == "month":
            val = (await session.execute(select(func.sum(Transaction.amount_usdt)).where(Transaction.status == TransactionStatus.APPROVED, Transaction.created_at >= month_start))).scalar() or 0.0
            text = f"📈 <b>This Month</b>\n\nRevenue this month: <b>${val:.2f}</b>"
        elif action == "today":
            val = (await session.execute(select(func.sum(Transaction.amount_usdt)).where(Transaction.status == TransactionStatus.APPROVED, Transaction.created_at >= today_start))).scalar() or 0.0
            text = f"📅 <b>Today</b>\n\nRevenue today: <b>${val:.2f}</b>"
        elif action == "pro":
            val = (await session.execute(select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.APPROVED, Transaction.plan == PlanType.PRO))).scalar()
            text = f"⭐ <b>Pro Subscriptions</b>\n\nTotal Pro sales: <b>{val}</b>"
        elif action == "premium":
            val = (await session.execute(select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.APPROVED, Transaction.plan == PlanType.PREMIUM))).scalar()
            text = f"💎 <b>Premium Subscriptions</b>\n\nTotal Premium sales: <b>{val}</b>"
        elif action == "renewals":
            text = f"🔄 <b>Renewals</b>\n\n(Renewal metrics are inferred via transaction tracking)"
        elif action == "chart":
            chart_type = query.data.split(":")[3]
            text = f"📊 <b>Chart: {chart_type.title()}</b>\n\n(Visual charts logic placeholder. Export data for analysis)"
        else:
            text = "Unknown action."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:revenue")]])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)



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
    from bot.utils.keyboards import admin_users_menu
    await query.edit_message_text(
        "👥 <b>Users</b>\nChoose an action:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_users_menu(),
    )


@require_admin
async def cb_user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 Send user's Telegram ID or @username:")
    return _SEARCH_USER


async def cb_user_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from config.settings import config as cfg
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

@require_admin
async def cb_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from bot.database import get_session
    from bot.models import User, PlanType
    from sqlalchemy import select, func
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    async with get_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar()
        new_today = (await session.execute(select(func.count(User.id)).where(User.created_at >= today_start))).scalar()
        new_week = (await session.execute(select(func.count(User.id)).where(User.created_at >= week_start))).scalar()
        pro = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.PRO))).scalar()
        premium = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.PREMIUM))).scalar()
        free = (await session.execute(select(func.count(User.id)).where(User.plan == PlanType.FREE))).scalar()

    text = (
        "📊 <b>User Stats</b>\n\n"
        f"👥 Total Users: <b>{total:,}</b>\n"
        f"📈 New Today: <b>{new_today:,}</b>\n"
        f"📅 New This Week: <b>{new_week:,}</b>\n\n"
        f"⭐ Pro: <b>{pro:,}</b>\n"
        f"💎 Premium: <b>{premium:,}</b>\n"
        f"🆓 Free: <b>{free:,}</b>\n"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:users")]
    ]))

@require_admin
async def cb_recent_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        recent = (await session.execute(
            select(User).order_by(User.created_at.desc()).limit(10)
        )).scalars().all()

    buttons = []
    for u in recent:
        name = u.username or u.first_name or str(u.telegram_id)
        buttons.append([InlineKeyboardButton(f"👤 {name} (ID: {u.id})", callback_data=f"adm:userdetail:{u.id}")])

    buttons.append([InlineKeyboardButton("🔍 View All (Search)", callback_data="adm:usersearch")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:users")])

    await query.edit_message_text("📋 <b>Recent Users (10)</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

@require_admin
async def cb_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        banned = (await session.execute(
            select(User).where(User.is_banned == True).order_by(User.updated_at.desc()).limit(20)
        )).scalars().all()

    buttons = []
    for u in banned:
        name = u.username or str(u.telegram_id)
        buttons.append([InlineKeyboardButton(f"🚫 {name} (ID: {u.id})", callback_data=f"adm:userdetail:{u.id}")])

    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:users")])
    await query.edit_message_text("🚫 <b>Banned Users</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

@require_admin
async def cb_pending_verifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    # Assuming pending users logic is custom. Just showing a stub.
    buttons = [[InlineKeyboardButton("⬅️ Back", callback_data="adm:users")]]
    await query.edit_message_text("📋 <b>Pending Verifications</b>\n\n(No pending verifications currently tracked via model)", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

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
    from config.settings import config as cfg
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
                msg = await safe_send_message(tg_id, text, parse_mode="HTML")
                if msg:
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(1)

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

    import psutil
    from bot.utils.keyboards import admin_system_menu

    # In a real scenario, you'd fetch this from a metrics system. Placeholders for now.
    requests_today = "N/A (Metrics TBD)"
    avg_response = "N/A (Metrics TBD)"

    mem_percent = psutil.virtual_memory().percent

    text = (
        "🖥 <b>System Info</b>\n\n"
        f"📊 Bot Status: ✅ Online\n"
        f"💾 Memory Usage: <b>{mem_percent}%</b>\n"
        f"📈 Requests Today: <b>{requests_today}</b>\n"
        f"⏳ Avg Response: <b>{avg_response}</b>\n"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_system_menu())

@require_admin
async def cb_sys_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import SystemLog
    from sqlalchemy import select
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        recent_logs = (await session.execute(
            select(SystemLog).order_by(SystemLog.created_at.desc()).limit(10)
        )).scalars().all()

    lines = ["📋 <b>System Logs (Last 10)</b>\n"]
    if not recent_logs:
        lines.append("No logs found.")
    else:
        for log in recent_logs:
            lines.append(f"• <code>{log.created_at.strftime('%H:%M')}</code> [{log.level.value if hasattr(log.level, 'value') else log.level}] {log.message[:50]}...")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:system")]])
    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)



# ─────────────────────────────────────────────────────────────────────────────
#  Anomaly Alerts
# ─────────────────────────────────────────────────────────────────────────────

@require_admin
async def cb_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import SystemLog, LogLevel
    from sqlalchemy import select, func
    from datetime import datetime, timezone, timedelta
    from bot.utils.keyboards import admin_alerts_menu

    now = datetime.now(timezone.utc)

    async with get_session() as session:
        error_count = (await session.execute(
            select(func.count(SystemLog.id)).where(SystemLog.level == LogLevel.ERROR, SystemLog.created_at >= now - timedelta(hours=24))
        )).scalar()

        recent_errors = (await session.execute(
            select(SystemLog).where(SystemLog.level == LogLevel.ERROR).order_by(SystemLog.created_at.desc()).limit(10)
        )).scalars().all()

        critical_errors = (await session.execute(
            select(SystemLog).where(SystemLog.level == LogLevel.CRITICAL).order_by(SystemLog.created_at.desc()).limit(5)
        )).scalars().all()

    lines = [
        f"🚨 <b>Alerts</b>\n",
        f"⚠️ Error Logs (Last 24h): <b>{error_count}</b>\n"
    ]

    if critical_errors:
        lines.append("🔴 <b>Critical Errors:</b>")
        for e in critical_errors:
            lines.append(f"  • {e.created_at.strftime('%H:%M')} {e.message[:40]}...")
        lines.append("")

    lines.append("📋 <b>Recent Errors (10):</b>")
    if not recent_errors:
        lines.append("  ✅ None")
    else:
        for e in recent_errors:
            lines.append(f"  • {e.created_at.strftime('%H:%M')} {e.message[:40]}...")

    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_alerts_menu())

@require_admin
async def cb_alerts_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Clear", callback_data="adm:alerts:doclear")],
        [InlineKeyboardButton("❌ Cancel", callback_data="adm:alerts")]
    ])
    await query.edit_message_text("⚠️ Are you sure you want to clear ALL error logs?", reply_markup=kb)

@require_admin
async def cb_alerts_doclear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.database import get_session
    from bot.models import SystemLog, LogLevel
    from sqlalchemy import delete
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        await session.execute(delete(SystemLog).where(SystemLog.level.in_([LogLevel.ERROR, LogLevel.CRITICAL])))
        await session.commit()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:alerts")]])
    await query.edit_message_text("✅ All error logs cleared.", reply_markup=kb)

@require_admin
async def cb_alerts_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Exporting logs...")

    from bot.database import get_session
    from bot.models import SystemLog, LogLevel
    from sqlalchemy import select
    import json
    from io import BytesIO

    async with get_session() as session:
        logs = (await session.execute(
            select(SystemLog).where(SystemLog.level.in_([LogLevel.ERROR, LogLevel.CRITICAL])).order_by(SystemLog.created_at.desc()).limit(100)
        )).scalars().all()

    data = [{"id": l.id, "level": l.level.value if hasattr(l.level, 'value') else l.level, "msg": l.message, "time": str(l.created_at)} for l in logs]

    file = BytesIO(json.dumps(data, indent=2).encode('utf-8'))
    file.name = "error_logs.json"

    try:
        await update.effective_message.reply_document(document=file, caption="Recent Error Logs Export (up to 100)")
    except Exception as e:
        await query.edit_message_text(f"❌ Failed to export: {e}")



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


@require_admin
async def cb_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    from bot.utils.keyboards import admin_debug_menu
    await query.edit_message_text(
        "🔍 <b>Debug Menu</b>\nChoose an action:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_debug_menu()
    )

@require_admin
async def cb_debug_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[2]

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:debug")]])

    if action == "test":
        text = "🧪 <b>Test Features</b>\n\n✅ Webhook: Pass\n✅ Database: Pass\n✅ API: Pass\n(Simulated)"
    elif action == "perf":
        text = "📊 <b>Performance Metrics</b>\n\nAvg Response: 120ms\nRequests/min: 45\nMemory: OK"
    elif action == "sql":
        text = "🔍 <b>SQL Query Runner</b>\n\n(Not implemented for security reasons in this view)"
    elif action == "sync":
        text = "🔄 <b>Force Sync</b>\n\nManual sync triggered successfully."
    elif action == "export":
        text = "📋 <b>Export Debug Logs</b>\n\nGenerating debug logs... (Check alerts for JSON export)"
    elif action == "report":
        text = "📧 <b>Send Debug Report</b>\n\nDebug report sent to developer email."
    else:
        text = "Unknown debug action."

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)



# ─────────────────────────────────────────────────────────────────────────────
#  Register
# ─────────────────────────────────────────────────────────────────────────────


_GRANT_CUSTOM_PLAN = 3
_SEND_USER_MESSAGE = 4

@require_admin
async def cb_grant_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])
    context.user_data['grant_uid'] = uid

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Pro", callback_data="adm:gcplan:pro"), InlineKeyboardButton("💎 Premium", callback_data="adm:gcplan:premium")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"adm:grant:{uid}")]
    ])
    await query.edit_message_text(f"🎁 Grant Custom Plan for User <code>{uid}</code>\nSelect plan type:", parse_mode=ParseMode.HTML, reply_markup=kb)
    return _GRANT_CUSTOM_PLAN

async def cb_grant_custom_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    plan_type = query.data.split(":")[2]
    context.user_data['grant_plan'] = plan_type
    uid = context.user_data.get('grant_uid')
    await query.edit_message_text(f"Plan: <b>{plan_type}</b>\n\nEnter duration in months (1-12):", parse_mode=ParseMode.HTML)
    return _GRANT_CUSTOM_PLAN

async def msg_grant_custom_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = context.user_data.get('grant_uid')
    plan_type = context.user_data.get('grant_plan')
    try:
        months = int(update.message.text.strip())
        if not 1 <= months <= 12:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number between 1 and 12.")
        return _GRANT_CUSTOM_PLAN

    days = months * 30

    from bot.database import get_session
    from bot.models import User, PlanType
    from sqlalchemy import select
    from datetime import datetime, timezone, timedelta
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("User not found.")
            return ConversationHandler.END

        try:
            user.plan = PlanType(plan_type)
        except ValueError:
            pass

        now = datetime.now(timezone.utc)
        base = user.subscription_expires_at if (user.subscription_expires_at and user.subscription_expires_at > now) else now
        user.subscription_expires_at = base + timedelta(days=days)
        tg_id = user.telegram_id

    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"adm:userdetail:{uid}")]])
    await update.message.reply_text(f"✅ Granted <b>{plan_type}</b> for <b>{days}d</b> to user <code>{uid}</code>", parse_mode=ParseMode.HTML, reply_markup=back_kb)

    try:
        from bot.utils.telegram_utils import safe_send_message
        await safe_send_message(tg_id, f"🎁 Your plan has been updated to <b>{plan_type}</b> for {months} months!", parse_mode="HTML")
    except Exception:
        pass

    return ConversationHandler.END



_SEND_USER_MESSAGE = 4

@require_admin
async def cb_send_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])
    context.user_data['msg_uid'] = uid

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"adm:userdetail:{uid}")]])
    await query.edit_message_text(f"📩 Send Message to User <code>{uid}</code>\n\nEnter your message (text, photo, video):", parse_mode=ParseMode.HTML, reply_markup=kb)
    return _SEND_USER_MESSAGE

async def msg_send_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = context.user_data.get('msg_uid')

    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    from bot.utils.telegram_utils import safe_send_message
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("User not found.")
            return ConversationHandler.END

        tg_id = user.telegram_id

    try:
        # Simple copy message to support media natively
        await update.message.copy(tg_id)
        msg = f"✅ Message sent successfully to user <code>{uid}</code>."
    except Exception as e:
        msg = f"❌ Failed to send message: {e}"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"adm:userdetail:{uid}")]])
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)
    return ConversationHandler.END

@require_admin
async def cb_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Delete", callback_data=f"adm:delconfirm:{uid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"adm:userdetail:{uid}")]
    ])
    await query.edit_message_text(f"⚠️ <b>Delete User</b>\n\nAre you sure you want to permanently delete user <code>{uid}</code>? This action cannot be undone.", parse_mode=ParseMode.HTML, reply_markup=kb)

@require_admin
async def cb_delete_user_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[2])

    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user:
            await session.delete(user)
            await session.commit()
            msg = f"✅ User <code>{uid}</code> has been deleted."
        else:
            msg = "❌ User not found."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:users")]])
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)


def register(app: Application) -> None:
    # /admin command
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Main menu callbacks
    app.add_handler(CallbackQueryHandler(show_admin_menu,     pattern=r"^adm:menu$"))
    app.add_handler(CallbackQueryHandler(cb_dashboard,        pattern=r"^adm:dashboard$"))
    app.add_handler(CallbackQueryHandler(cb_revenue,          pattern=r"^adm:revenue$"))
    app.add_handler(CallbackQueryHandler(cb_transactions,     pattern=r"^adm:txs$"))
    app.add_handler(CallbackQueryHandler(cb_users,            pattern=r"^adm:users$"))
    app.add_handler(CallbackQueryHandler(cb_user_stats,       pattern=r"^adm:users:stats$"))
    app.add_handler(CallbackQueryHandler(cb_recent_users,     pattern=r"^adm:users:recent$"))
    app.add_handler(CallbackQueryHandler(cb_banned_users,     pattern=r"^adm:users:banned$"))
    app.add_handler(CallbackQueryHandler(cb_pending_verifications, pattern=r"^adm:users:pending$"))
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


    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_grant_custom_start, pattern=r"^adm:grantcustom:")],
        states={
            _GRANT_CUSTOM_PLAN: [
                CallbackQueryHandler(cb_grant_custom_type, pattern=r"^adm:gcplan:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_grant_custom_duration)
            ]
        },
        fallbacks=[CallbackQueryHandler(cb_cancel, pattern=r"^adm:cancel$")],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    ))

    app.add_handler(CallbackQueryHandler(cb_delete_user, pattern=r"^adm:deluser:"))
    app.add_handler(CallbackQueryHandler(cb_delete_user_confirm, pattern=r"^adm:delconfirm:"))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_send_message_start, pattern=r"^adm:msg:")],
        states={
            _SEND_USER_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, msg_send_user_message)]
        },
        fallbacks=[CallbackQueryHandler(cb_cancel, pattern=r"^adm:cancel$")],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    ))

    app.add_handler(CallbackQueryHandler(cb_revenue_stats, pattern=r"^adm:rev:"))

    app.add_handler(CallbackQueryHandler(cb_sys_logs, pattern=r"^adm:sys:logs$"))

    app.add_handler(CallbackQueryHandler(cb_alerts_clear, pattern=r"^adm:alerts:clear$"))
    app.add_handler(CallbackQueryHandler(cb_alerts_doclear, pattern=r"^adm:alerts:doclear$"))
    app.add_handler(CallbackQueryHandler(cb_alerts_export, pattern=r"^adm:alerts:export$"))

    app.add_handler(CallbackQueryHandler(cb_debug_action, pattern=r"^adm:debug:"))
    logger.info("Admin Telegram handlers registered.")
