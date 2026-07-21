"""SocialtoFeed — /status command v3.1"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from bot.utils.keyboards import status_keyboard
logger = logging.getLogger(__name__)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("user")
    if not user: return
    lang = user.language; now = datetime.now(timezone.utc); f = lang=="fa"
    from bot.services.plan_service import get_user_features
    features = await get_user_features(user)
    max_acc = features.get("max_accounts",5)
    acc_count = posts_today = bm_used = 0
    try:
        from bot.database import get_session
        from bot.models import Account, SentPost, Bookmark
        from sqlalchemy import select, func
        async with get_session() as session:
            acc_count=(await session.execute(select(func.count()).select_from(Account).where(Account.user_id==user.id,Account.is_active==True))).scalar() or 0
            today=now.replace(hour=0,minute=0,second=0,microsecond=0)
            posts_today=(await session.execute(select(func.count()).select_from(SentPost).join(Account,SentPost.account_id==Account.id).where(Account.user_id==user.id,SentPost.sent_at>=today))).scalar() or 0
            bm_used=(await session.execute(select(func.count()).select_from(Bookmark).where(Bookmark.user_id==user.id))).scalar() or 0
    except Exception: pass
    pn={"fa":{"free":"🆓 رایگان","pro":"⭐️ پرو","premium":"💎 پریمیوم"},"en":{"free":"🆓 Free","pro":"⭐️ Pro","premium":"💎 Premium"}}.get(lang,{"free":"🆓 Free","pro":"⭐️ Pro","premium":"💎 Premium"}).get(user.plan.value,user.plan.value.title())
    credit_info=""
    if user.credit_expires_at and user.credit_expires_at>now and user.credit_plan:
        d=(user.credit_expires_at-now).days
        cn={"fa":{"pro":"⭐️ پرو","premium":"💎 پریمیوم"},"en":{"pro":"⭐️ Pro","premium":"💎 Premium"}}.get(lang,{"pro":"Pro","premium":"Premium"}).get(user.credit_plan.value,user.credit_plan.value)
        credit_info=f"\n🎁 {'اعتبار' if f else 'Credit'}: <b>{cn}</b> — {d} {'روز' if f else 'days'}"
    expiry_info=""
    if user.subscription_expires_at:
        d=(user.subscription_expires_at-now).days
        if d>0: expiry_info=f"\n📅 {'انقضا' if f else 'Expires'}: <b>{d} {'روز' if f else 'days'}</b>"
        elif user.grace_until and user.grace_until>now:
            gh=int((user.grace_until-now).total_seconds()/3600)
            expiry_info=f"\n⚠️ Grace — {gh}h"
        else: expiry_info="\n❌ "+("منقضی" if f else "Expired")
    bml=features.get("bookmark_limit",0)
    bml_display = "♾" if bml == 0 else str(bml)   # v3.3: 0 = unlimited
    if f:
        msg=(f"📊 <b>وضعیت اشتراک</b>\n\n👤 پلن: <b>{pn}</b>{credit_info}{expiry_info}\n\n"
             f"📱 اکانت‌ها: <b>{acc_count}/{max_acc}</b>\n"
             f"📨 پست‌های امروز: <b>{posts_today}</b>\n"
             f"🔖 Bookmark: <b>{bm_used}/{bml_display}</b>")
    else:
        msg=(f"📊 <b>Subscription Status</b>\n\n👤 Plan: <b>{pn}</b>{credit_info}{expiry_info}\n\n"
             f"📱 Accounts: <b>{acc_count}/{max_acc}</b>\n"
             f"📨 Posts today: <b>{posts_today}</b>\n"
             f"🔖 Bookmarks: <b>{bm_used}/{bml_display}</b>")
    if user.plan.value=="premium":
        ai_c=getattr(user,"daily_ai_count",0)
        msg+=f"\n🤖 AI: <b>{ai_c}</b>/{'نامحدود' if f else 'unlimited'}"
    if user.plan.value in("pro","premium"):
        msg+=f"\n✅ {'لینک دانلود' if f else 'Download links'}"
    if user.plan.value=="premium":
        msg+=f"\n✅ {'هوش مصنوعی' if f else 'AI features'} · {'دانلود فایل' if f else 'File download'}"
    if user.plan.value=="free":
        msg+=f"\n\n💡 {'ارتقا به پرو' if f else 'Upgrade to Pro ⭐️'} → /subscription"
    await update.message.reply_text(msg,parse_mode=ParseMode.HTML,reply_markup=status_keyboard(lang))

def register(app: Application) -> None:
    from bot.middlewares.auth import auth_middleware
    app.add_handler(CommandHandler("status", auth_middleware(cmd_status)))
    logger.info("Status handler registered.")
