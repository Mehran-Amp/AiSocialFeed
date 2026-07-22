"""SocialtoFeed — Crypto Payment Handler v3.1
CoinEx auto-verify. Exchange name never shown to users.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from bot.models import PlanType, SubscriptionPeriod
from bot.utils.keyboards import subscription_keyboard, period_keyboard
logger = logging.getLogger(__name__)

# INC-1 fix: prices are now read from DB PlanConfig so admin panel changes
# take effect immediately. PLAN_PRICES hardcoded dict removed.
async def _get_prices(plan_str: str) -> dict:
    """Return {monthly, biannual, yearly} prices from DB for a given plan slug."""
    try:
        from bot.database import get_session
        from bot.models import PlanConfig
        from sqlalchemy import select
        async with get_session() as session:
            cfg = (await session.execute(
                select(PlanConfig).where(PlanConfig.plan == PlanType(plan_str))
            )).scalar_one_or_none()
            if cfg:
                return {
                    "monthly":  float(cfg.price_monthly  or 0),
                    "biannual": float(cfg.price_biannual or 0),
                    "yearly":   float(cfg.price_yearly   or 0),
                }
    except Exception as e:
        logger.warning(f"[crypto_payment] DB price lookup failed: {e}")
    return {}

async def _get_amount(plan_str: str, period_str: str) -> float:
    """Return single price value from DB."""
    return (await _get_prices(plan_str)).get(period_str, 0.0)

async def cb_select_period(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    plan_str=query.data.split(":")[2]; lang=user.language; f=lang=="fa"
    prices=await _get_prices(plan_str)
    pn={"fa":{"pro":"⭐️ پرو","premium":"💎 پریمیوم"},"en":{"pro":"⭐️ Pro","premium":"💎 Premium"}}.get(lang,{"pro":"Pro","premium":"Premium"}).get(plan_str,plan_str)
    txt=(f"📅 <b>{'انتخاب دوره' if f else 'Select period'} — {pn}</b>")
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=period_keyboard(plan_str,lang,prices))

async def cb_select_network(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    parts=query.data.split(":"); plan_str=parts[2]; period_str=parts[3]; lang=user.language; f=lang=="fa"
    amount=await _get_amount(plan_str, period_str)
    context.user_data.update({"pending_plan":plan_str,"pending_period":period_str,"pending_amount":amount})
    txt=(f"💳 <b>{'پرداخت رمزارز' if f else 'Crypto Payment'}</b>\n\n"
         f"{'مبلغ' if f else 'Amount'}: <b>{amount:.0f} USDT</b>\n\n"
         f"{'شبکه انتقال' if f else 'Select network'}:")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ TRC20 (TRON) — "+("سریع‌ترین" if f else "Fastest"),callback_data=f"pay:network:{plan_str}:{period_str}:TRC20")],
        [InlineKeyboardButton("🔵 BEP20 (BSC)",callback_data=f"pay:network:{plan_str}:{period_str}:BEP20")],
        [InlineKeyboardButton("⬡ ERC20 (Ethereum)",callback_data=f"pay:network:{plan_str}:{period_str}:ERC20")],
        [InlineKeyboardButton("⬅️ "+("بازگشت" if f else "Back"),callback_data=f"pay:plan:{plan_str}")],
    ])
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=kb)

async def cb_network_warning(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    parts=query.data.split(":"); plan_str=parts[2]; period_str=parts[3]; network=parts[4]
    lang=user.language; f=lang=="fa"
    nets={"TRC20":"TRC20 (TRON)","BEP20":"BEP20 (BSC)","ERC20":"ERC20 (ETH)"}
    nl=nets.get(network,network)
    txt=(f"⚠️ <b>{'تأیید شبکه' if f else 'Confirm Network'}</b>\n\n"
         f"{'شبکه' if f else 'Network'}: <b>{nl}</b>\n\n"
         f"{'⚠️ فقط از این شبکه ارسال کن!' if f else '⚠️ Only send via this network!'}\n"
         f"{'شبکه اشتباه = از دست رفتن پول' if f else 'Wrong network = lost funds'}")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ "+("مطمئنم" if f else "Confirmed"),callback_data=f"pay:confirm:{plan_str}:{period_str}:{network}")],
        [InlineKeyboardButton("↩️ "+("تغییر شبکه" if f else "Change"),callback_data=f"pay:period:{plan_str}:{period_str}")],
    ])
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=kb)

async def cb_generate_address(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    parts=query.data.split(":"); plan_str=parts[2]; period_str=parts[3]; network=parts[4]
    lang=user.language; f=lang=="fa"
    amount=await _get_amount(plan_str, period_str)
    await query.edit_message_text("⏳ "+("در حال ساخت آدرس..." if f else "Generating address..."))
    from bot.services.payment_service import get_deposit_address, start_payment_monitor
    addr_info=await get_deposit_address(user.id, network, amount)
    if not addr_info:
        from bot.utils.keyboards import home_button
        await query.edit_message_text("❌ "+("خطا. دوباره امتحان کن." if f else "Error. Please try again."),
                                      reply_markup=home_button(lang))
        return
    address=addr_info["address"]; nl=addr_info["network_label"]; exp=addr_info["expires_at"]
    from bot.handlers.crypto_payment import _create_pending_transaction
    from bot.models import PlanType as PT, SubscriptionPeriod as SP
    try: plan=PT(plan_str); period=SP(period_str)
    except ValueError:
        from bot.utils.keyboards import home_button
        await query.edit_message_text("❌ Error", reply_markup=home_button(lang)); return
    tx_id=await _create_pending_transaction(user,plan,period,amount,network,address,exp)
    await start_payment_monitor(tx_id)
    pn={"fa":{"pro":"⭐️ پرو","premium":"💎 پریمیوم"},"en":{"pro":"Pro","premium":"Premium"}}.get(lang,{"pro":"Pro","premium":"Premium"}).get(plan_str,plan_str)
    txt=(f"💳 <b>{'پرداخت رمزارز' if f else 'Crypto Payment'}</b>\n\n"
         f"📦 {'پلن' if f else 'Plan'}: <b>{pn}</b>\n"
         f"💰 {'مبلغ' if f else 'Amount'}: <b>{amount:.0f} USDT</b>\n"
         f"🌐 {'شبکه' if f else 'Network'}: <b>{nl}</b>\n"
         f"⏰ {'انقضا' if f else 'Expires'}: <b>{exp.strftime('%H:%M')} UTC</b>\n\n"
         f"📋 <b>{'آدرس کیف پول' if f else 'Wallet Address'}:</b>\n"
         f"<code>{address}</code>\n\n"
         f"{'✅ بعد از تأیید، اشتراک خودکار فعال میشه' if f else '✅ Subscription auto-activates after confirmation'}\n"
         f"{'⚠️ فقط USDT روی' if f else '⚠️ Only USDT via'} {network}")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 "+("بررسی پرداخت" if f else "Check Payment"),callback_data=f"pay:check:{tx_id}")],
        [InlineKeyboardButton("❓ FAQ",callback_data="pay:faq")],
        [InlineKeyboardButton("❌ "+("لغو" if f else "Cancel"),callback_data=f"pay:cancel:{tx_id}")],
    ])
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=kb,disable_web_page_preview=True)

async def cb_check_payment(update, context):
    query=update.callback_query
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; f=lang=="fa"
    await query.answer("🔍 "+("بررسی..." if f else "Checking..."),show_alert=False)
    tx_id=int(query.data.split(":")[-1])
    from bot.handlers.crypto_payment import _get_transaction
    from bot.services.payment_service import check_deposit, activate_subscription_safe
    tx=await _get_transaction(tx_id, user.id)
    if not tx:
        await query.answer("❌ Not found", show_alert=True); return
    result=await check_deposit(tx["address"],tx["network"],tx["amount"],tx["created_at"])
    if result and result["enough"]:
        await activate_subscription_safe(tx_id, result, reviewed_by="auto:coinex")
        await query.answer("✅ "+("تأیید شد!" if f else "Confirmed!"),show_alert=True)
    elif result:
        await query.answer(f"⏳ {result.get('received',0):.2f}/{tx['amount']:.0f} USDT",show_alert=True)
    else:
        await query.answer("⏳ "+("هنوز دریافت نشده" if f else "Not received yet"),show_alert=True)

async def cb_payment_faq(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    lang=user.language if user else "en"; f=lang=="fa"
    txt=(f"❓ <b>{'سوالات متداول' if f else 'Payment FAQ'}</b>\n\n"
         f"<b>{'چقدر طول میکشه?' if f else 'How long?'}</b>\n"
         f"TRC20: 1-3 {'دقیقه' if f else 'min'} ⚡️ | BEP20: 5-15 | ERC20: 5-30\n\n"
         f"<b>{'آدرس چقدر معتبره?' if f else 'Address validity?'}</b>\n"
         f"6 {'ساعت' if f else 'hours'}\n\n"
         f"<b>{'کمتر فرستادم؟' if f else 'Sent less?'}</b>\n"
         f"{'سیستم منتظر میمونه — تکمیل کن' if f else 'System waits — complete it'}\n\n"
         f"<b>{'بیشتر فرستادم؟' if f else 'Sent more?'}</b>\n"
         f"{'اشتراک فعال میشه' if f else 'Subscription activates'}")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️",callback_data="pay:back:plans")]]))

async def _create_pending_transaction(user, plan, period, amount, network, address, expires_at):
    from bot.database import get_session
    from bot.models import Transaction, TransactionMethod, TransactionStatus
    async with get_session() as session:
        tx=Transaction(user_id=user.id,plan=plan,period=period,amount_usdt=amount,
            payment_method=TransactionMethod.CRYPTO,status=TransactionStatus.PENDING,
            deposit_address=address,network=network,address_expires_at=expires_at,
            address_generated_at=datetime.now(timezone.utc))
        session.add(tx); await session.flush()
        return tx.id

async def _get_transaction(tx_id, user_id):
    from bot.database import get_session
    from bot.models import Transaction
    from sqlalchemy import select
    async with get_session() as session:
        tx=(await session.execute(select(Transaction).where(Transaction.id==tx_id,Transaction.user_id==user_id))).scalar_one_or_none()
        if not tx: return None
        return {"id":tx.id,"address":tx.deposit_address,"network":tx.network,
                "amount":float(tx.amount_usdt),"created_at":tx.address_generated_at or tx.created_at,
                "plan":tx.plan,"period":tx.period,"user_id":tx.user_id}

async def cb_cancel_payment(update, context):
    """Cancel an active crypto payment and mark transaction as rejected."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("user")
    if not user:
        return
    lang = user.language
    f = lang == "fa"
    parts = query.data.split(":")
    tx_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if tx_id:
        from bot.database import get_session
        from bot.models import Transaction, TransactionStatus
        from sqlalchemy import select
        async with get_session() as session:
            tx = (await session.execute(
                select(Transaction).where(
                    Transaction.id == tx_id,
                    Transaction.user_id == user.id,
                    Transaction.status == TransactionStatus.PENDING,
                )
            )).scalar_one_or_none()
            if tx:
                tx.status = TransactionStatus.REJECTED
                tx.reject_reason = "Cancelled by user"
    from bot.utils.keyboards import subscription_keyboard
    await query.edit_message_text(
        "❌ " + ("پرداخت لغو شد." if f else "Payment cancelled."),
        reply_markup=subscription_keyboard(lang),
    )


async def cb_back_to_plans_crypto(update, context):
    """Handle pay:back:plans from crypto flow — back to plan selection."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    from bot.utils.keyboards import subscription_keyboard
    await query.edit_message_reply_markup(reply_markup=subscription_keyboard(lang))


def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(cb_select_period,    pattern=r"^pay:plan:"))
    app.add_handler(CallbackQueryHandler(cb_select_network,   pattern=r"^pay:period:"))
    app.add_handler(CallbackQueryHandler(cb_network_warning,  pattern=r"^pay:network:"))
    app.add_handler(CallbackQueryHandler(cb_generate_address, pattern=r"^pay:confirm:"))
    app.add_handler(CallbackQueryHandler(cb_check_payment,    pattern=r"^pay:check:"))
    app.add_handler(CallbackQueryHandler(cb_payment_faq,      pattern=r"^pay:faq"))
    app.add_handler(CallbackQueryHandler(cb_cancel_payment,   pattern=r"^pay:cancel:"))
    # Note: pay:back:plans is handled by payment.py (registered first) — no duplicate needed here
    logger.info("Crypto payment handlers registered.")
