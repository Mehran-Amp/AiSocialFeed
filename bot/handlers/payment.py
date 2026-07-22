"""
SocialtoFeed — Payment Handler
Subscription plans display, USDT payment flow, TxID/screenshot submission.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.database import get_session
from bot.models import (
    PlanConfig, PlanType, SubscriptionPeriod,
    Transaction, TransactionMethod, TransactionStatus, USDTAddress, User,
)
from bot.utils.keyboards import main_menu, period_selection, plan_selection
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t

logger = logging.getLogger(__name__)

WAITING_NETWORK = 20
WAITING_CONFIRM = 21


# ─────────────────────────────────────────────
#  Show Plans
# ─────────────────────────────────────────────

async def show_plans(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
) -> None:
    lang = user.language

    async with get_session() as session:
        from sqlalchemy import select
        configs = (await session.execute(select(PlanConfig))).scalars().all()

    cfg_map = {c.plan: c for c in configs}

    def price_line(plan: PlanType) -> str:
        cfg = cfg_map.get(plan)
        if not cfg or cfg.price_monthly == 0:
            return "Free"
        return f"${cfg.price_monthly:.0f}/mo • ${cfg.price_biannual:.0f}/6mo • ${cfg.price_yearly:.0f}/yr"

    pro_cfg = cfg_map.get(PlanType.PRO)
    prem_cfg = cfg_map.get(PlanType.PREMIUM)

    text = (
        f"💳 <b>Subscription Plans</b>\n\n"
        f"🆓 <b>Free</b> — {cfg_map.get(PlanType.FREE, {}).max_accounts if PlanType.FREE in cfg_map else 5} accounts\n\n"
        f"⭐️ <b>Pro</b> — {pro_cfg.max_accounts if pro_cfg else 35} accounts\n"
        f"   {price_line(PlanType.PRO)}\n"
        f"   ✅ Custom intervals  ✅ Digest  ✅ CSV export\n\n"
        f"💎 <b>Premium</b> — {prem_cfg.max_accounts if prem_cfg else 100} accounts\n"
        f"   {price_line(PlanType.PREMIUM)}\n"
        f"   ✅ AI features  ✅ Video download  ✅ TikTok/LinkedIn/Reddit\n"
        f"   ✅ Channel forward  ✅ Stats  ✅ JSON export\n\n"
        f"Your current plan: <b>{user.plan.value.capitalize()}</b>"
    )

    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=plan_selection(lang),
    )


# ─────────────────────────────────────────────
#  Plan → Period → Payment Method
# ─────────────────────────────────────────────

async def cb_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return

    lang = user.language
    parts = query.data.split(":")

    if parts[1] == "plans":
        # Back to plan list
        await query.edit_message_reply_markup(reply_markup=plan_selection(lang))

    elif parts[1] == "plan":
        plan_name = parts[2]
        await query.edit_message_reply_markup(
            reply_markup=period_selection(plan_name, lang)
        )

    elif parts[1] == "period":
        plan_name = parts[2]
        period_name = parts[3]
        context.user_data["pending_plan"] = plan_name
        context.user_data["pending_period"] = period_name

        # Get price and addresses
        plan_enum = PlanType(plan_name)
        period_enum = SubscriptionPeriod(period_name)

        async with get_session() as session:
            from sqlalchemy import select
            cfg = (await session.execute(
                select(PlanConfig).where(PlanConfig.plan == plan_enum)
            )).scalar_one_or_none()

            addresses = (await session.execute(
                select(USDTAddress).where(USDTAddress.is_active == True)
                .order_by(USDTAddress.is_default.desc())
            )).scalars().all()

        price = 0.0
        if cfg:
            price = {
                SubscriptionPeriod.MONTHLY: cfg.price_monthly,
                SubscriptionPeriod.BIANNUAL: cfg.price_biannual,
                SubscriptionPeriod.YEARLY: cfg.price_yearly,
            }.get(period_enum, 0.0)

        context.user_data["pending_amount"] = price

        if not addresses:
            await query.edit_message_text(
                "⚠️ Payment is temporarily unavailable. Please try later.",
                parse_mode=ParseMode.HTML,
            )
            return

        addr_text = "\n".join(
            f"{'🔹' if a.is_default else '▫️'} <b>{a.label}</b>\n   <code>{a.address}</code>"
            for a in addresses
        )

        await query.edit_message_text(
            t("subscription.payment_instructions", lang,
              amount=f"{price:.2f}", addresses=addr_text),
            parse_mode=ParseMode.HTML,
            reply_markup=_payment_buttons(plan_name, period_name, lang),
        )


def _payment_buttons(plan: str, period: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("subscription.select_network", lang),
            callback_data=f"pay:txid:{plan}:{period}"
        )],
        [InlineKeyboardButton(
            t("subscription.confirm_network", lang),
            callback_data=f"pay:screenshot:{plan}:{period}"
        )],
        [InlineKeyboardButton(
            "💳 Mastercard — Coming Soon",
            callback_data="pay:mastercard"
        )],
        [InlineKeyboardButton(t("menu.back", lang), callback_data=f"sub:plan:{plan}")],
    ])


# ─────────────────────────────────────────────
#  Payment Proof Collection
# ─────────────────────────────────────────────

async def cb_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    parts = query.data.split(":")

    if parts[1] == "mastercard":
        await query.edit_message_text(
            t("payment.mastercard_coming", lang),
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    proof_type = parts[1]  # "txid" or "screenshot"
    plan_name = parts[2]
    period_name = parts[3]

    context.user_data["proof_type"] = proof_type
    context.user_data["pending_plan"] = plan_name
    context.user_data["pending_period"] = period_name

    if proof_type == "txid":
        await query.edit_message_text(t("subscription.txid_prompt", lang))
        return WAITING_NETWORK
    else:
        await query.edit_message_text(t("subscription.screenshot_prompt", lang))
        return WAITING_CONFIRM


async def receive_txid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    txid = update.message.text.strip()
    lang = user.language

    # Basic TxID validation
    if len(txid) < 20:
        await safe_send_message(
            update.effective_user.id,
            "⚠️ Invalid TxID. Please check and try again.",
        )
        return WAITING_NETWORK

    # Check duplicate TxID
    async with get_session() as session:
        from sqlalchemy import select
        existing = (await session.execute(
            select(Transaction).where(Transaction.txid == txid)
        )).scalar_one_or_none()

        if existing:
            await safe_send_message(
                update.effective_user.id,
                "⚠️ This TxID has already been submitted.",
                reply_markup=main_menu(lang),
            )
            return ConversationHandler.END

    ref = await _create_transaction(
        user=user,
        txid=txid,
        screenshot_path=None,
        plan=context.user_data.get("pending_plan"),
        period=context.user_data.get("pending_period"),
        amount=context.user_data.get("pending_amount", 0.0),
    )

    await safe_send_message(
        update.effective_user.id,
        t("subscription.submitted", lang, ref=ref),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(lang),
    )

    # Notify admin
    from bot.utils.telegram_utils import send_admin_alert
    await send_admin_alert(
        f"💰 <b>New Payment Request</b>\n\n"
        f"User: {user.telegram_id} (@{user.username})\n"
        f"Plan: {context.user_data.get('pending_plan')} / "
        f"{context.user_data.get('pending_period')}\n"
        f"Amount: ${context.user_data.get('pending_amount', 0):.2f} USDT\n"
        f"TxID: <code>{txid}</code>\n"
        f"Ref: <code>{ref}</code>"
    )

    _clear_payment_context(context)
    return ConversationHandler.END


async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language

    if not update.message.photo and not update.message.document:
        await safe_send_message(
            update.effective_user.id,
            "⚠️ Please send an image or document.",
        )
        return WAITING_CONFIRM

    # Get file
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        ext = "jpg"
    else:
        doc = update.message.document
        ext = doc.file_name.split(".")[-1].lower() if doc.file_name else "jpg"
        if ext not in ("jpg", "jpeg", "png", "pdf"):
            await safe_send_message(
                update.effective_user.id,
                "⚠️ Only JPG, PNG or PDF allowed.",
            )
            return WAITING_CONFIRM
        file_id = doc.file_id

    # Save file_id as reference (actual file stored in Telegram)
    screenshot_ref = f"tg:{file_id}"

    ref = await _create_transaction(
        user=user,
        txid=None,
        screenshot_path=screenshot_ref,
        plan=context.user_data.get("pending_plan"),
        period=context.user_data.get("pending_period"),
        amount=context.user_data.get("pending_amount", 0.0),
    )

    await safe_send_message(
        update.effective_user.id,
        t("subscription.submitted", lang, ref=ref),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(lang),
    )

    # Notify admin with screenshot
    from bot.utils.telegram_utils import get_bot, send_admin_alert
    await send_admin_alert(
        f"💰 <b>New Payment Request (Screenshot)</b>\n\n"
        f"User: {user.telegram_id} (@{user.username})\n"
        f"Plan: {context.user_data.get('pending_plan')} / "
        f"{context.user_data.get('pending_period')}\n"
        f"Amount: ${context.user_data.get('pending_amount', 0):.2f} USDT\n"
        f"Ref: <code>{ref}</code>"
    )
    # Forward screenshot to admin
    bot = get_bot()
    try:
        if update.message.photo:
            await bot.send_photo(
                chat_id=from_config_admin_id(),
                photo=file_id,
                caption=f"Screenshot for ref: {ref}",
            )
        else:
            await bot.send_document(
                chat_id=from_config_admin_id(),
                document=file_id,
                caption=f"Receipt for ref: {ref}",
            )
    except Exception as e:
        logger.error(f"Failed to forward screenshot to admin: {e}")

    _clear_payment_context(context)
    return ConversationHandler.END


def from_config_admin_id() -> int:
    from config import config
    return config.telegram.admin_id


async def _create_transaction(
    user: User,
    txid: Optional[str],
    screenshot_path: Optional[str],
    plan: Optional[str] = None,
    period: Optional[str] = None,
    amount: float = 0.0,
) -> str:
    """
    Fixed version of _create_transaction.
    Takes explicit plan/period/amount instead of reading from user.plan.
    """
    from bot.models import Transaction, PlanType, SubscriptionPeriod, USDTAddress, TransactionMethod, TransactionStatus
    from sqlalchemy import select

    async with get_session() as session:
        addr = (await session.execute(
            select(USDTAddress).where(
                USDTAddress.is_active == True,
                USDTAddress.is_default == True,
            )
        )).scalar_one_or_none()

        tx = Transaction(
            user_id=user.id,
            plan=PlanType(plan) if plan else user.plan,
            period=SubscriptionPeriod(period) if period else SubscriptionPeriod.MONTHLY,
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


def _clear_payment_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ("proof_type", "pending_plan", "pending_period", "pending_amount"):
        context.user_data.pop(key, None)


async def cb_back_to_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pay:back:plans — go back to plan selection screen."""
    query = update.callback_query
    await query.answer()
    user: Optional[User] = context.user_data.get("user")
    lang = user.language if user else "en"
    from bot.utils.keyboards import plan_selection
    await query.edit_message_reply_markup(reply_markup=plan_selection(lang))


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────


async def cb_coming_soon(update, context):
    query=update.callback_query
    user=context.user_data.get("user")
    lang=user.language if user else "en"
    fa=lang=="fa"
    method=query.data.split(":")[-1] if ":" in query.data else ""
    labels={"card":"Credit Card","apple":"Apple Pay","google":"Google Pay"}
    m=labels.get(method,method)
    t1=f"{m} در حال توسعه است." if fa else f"{m} is coming soon. Use Crypto for now."
    await query.answer(f"🔜 {t1}",show_alert=True)


async def cb_pay_method(update, context):
    """pay:method:<plan>:<period>:crypto → goes to crypto payment flow"""
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    parts=query.data.split(":")
    plan=parts[2] if len(parts)>2 else "pro"
    period=parts[3] if len(parts)>3 else "monthly"
    # Route to crypto flow
    query.data=f"pay:period:{plan}:{period}"
    from bot.handlers.crypto_payment import cb_select_network
    await cb_select_network(update,context)


def register(app: Application) -> None:
    # Plan/period selection callbacks — handles both "sub:" and "pay:back:plans"
    # v4.2.1 fix: cb_subscription (below) is legacy pre-v4.2 code with no "compare"
    # or "history" case. It was registered here with pattern=r"^sub:" and, since
    # payment.py registers before profile.py in main.py, it silently intercepted
    # every sub:compare / sub:history tap meant for profile.py's cb_sub, which
    # DOES handle those. Removed from registration.
    app.add_handler(CallbackQueryHandler(cb_back_to_plans, pattern=r"^pay:back:plans$"))

    # Payment proof conversation
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_pay, pattern=r"^pay:(txid|screenshot|mastercard):")],
        states={
            WAITING_NETWORK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_txid),
            ],
            WAITING_CONFIRM: [
                MessageHandler(
                    (filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
                    receive_screenshot,
                ),
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    logger.info("Payment handlers registered.")
    app.add_handler(CallbackQueryHandler(cb_coming_soon, pattern=r"^pay:coming_soon:"))
    app.add_handler(CallbackQueryHandler(cb_pay_method,  pattern=r"^pay:method:"))
