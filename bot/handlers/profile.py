"""SocialtoFeed — Profile Handler v4.2"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from bot.database import get_session
from bot.models import PlanType, User
from bot.utils.keyboards import (
    ai_features_menu, ai_translate_menu, ai_chat_locked_keyboard,
    back_button, compare_plans_keyboard, help_menu,
    main_menu, profile_menu, settings_menu,
    settings_locked_upgrade, subscription_menu,
    ticket_subjects,
)
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t

logger = logging.getLogger(__name__)


def _plan_str(user): return user.plan.value if hasattr(user.plan,"value") else str(user.plan)
def is_persian(lang: str) -> bool: return lang == "fa"


# ── SHOW PROFILE ──────────────────────────────────────────────────────────────

async def show_profile(update, context, user):
    lang=user.language; fa=is_persian(lang); plan=_plan_str(user)
    icon={"free":"🆓","pro":"⭐️","premium":"💎"}.get(plan,"")
    name=getattr(user,"first_name",None) or "User"
    exp=""
    if user.subscription_expires_at:
        days=(user.subscription_expires_at-datetime.now(timezone.utc)).days
        day_w="روز" if fa else "days"
        exp_w="انقضا" if fa else "Expires"
        exp=f"\n📅 {exp_w}: {max(days,0)} {day_w}"
    text=f"👤 <b>{name} {icon} {plan.capitalize()}</b>{exp}"
    await safe_send_message(update.effective_user.id,text,parse_mode=ParseMode.HTML,reply_markup=profile_menu(lang))


# ── SUBSCRIPTION ──────────────────────────────────────────────────────────────

async def _show_subscription(query, user):
    lang=user.language; fa=is_persian(lang); plan=_plan_str(user)
    icon={"free":"🆓","pro":"⭐️","premium":"💎"}.get(plan,"")
    expires_days=None; price_monthly=0.0
    if user.subscription_expires_at:
        expires_days=max((user.subscription_expires_at-datetime.now(timezone.utc)).days,0)
    try:
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import PlanConfig
            cfg=(await s.execute(select(PlanConfig).where(PlanConfig.plan==user.plan))).scalar_one_or_none()
            if cfg: price_monthly=float(cfg.price_monthly or 0)
    except Exception: pass
    t1="اشتراک" if fa else "Subscription"
    t2="پلن فعلی" if fa else "Current Plan"
    txt=f"💳 <b>{t1}</b>\n\n📌 {t2}: {icon} <b>{plan.upper()}</b>\n"
    if expires_days is not None:
        t3="انقضا" if fa else "Expires"; t4="روز" if fa else "days"
        txt+=f"📅 {t3}: <b>{expires_days} {t4}</b>\n"
    if price_monthly:
        t5="قیمت" if fa else "Price"; t6="ماه" if fa else "month"
        txt+=f"💰 {t5}: <b>${price_monthly:.0f}/{t6}</b>"
    await query.edit_message_text(txt,parse_mode=ParseMode.HTML,
        reply_markup=subscription_menu(lang,plan,expires_days,price_monthly))


# ── PROFILE CALLBACK ──────────────────────────────────────────────────────────

async def cb_profile(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; fa=is_persian(lang); plan=_plan_str(user)
    parts=query.data.split(":"); action=parts[1] if len(parts)>1 else ""

    if action=="menu":
        icon={"free":"🆓","pro":"⭐️","premium":"💎"}.get(plan,"")
        name=getattr(user,"first_name","User")
        await query.edit_message_text(f"👤 <b>{name} {icon} {plan.capitalize()}</b>",
            parse_mode=ParseMode.HTML,reply_markup=profile_menu(lang))

    elif action=="subscription":
        await _show_subscription(query,user)

    elif action=="referral":
        from bot.handlers.referral import show_referral
        await show_referral(update,context,user)

    elif action=="settings":
        ai_count=sum([user.ai_summarize,user.ai_translate,user.ai_categorize,user.ai_spam_tag])
        t1="تنظیمات" if fa else "Settings"
        await query.edit_message_text(f"⚙️ <b>{t1}</b>",parse_mode=ParseMode.HTML,
            reply_markup=settings_menu(lang,plan,
                spam_filter=getattr(user,"hide_spam_posts",False),
                email_digest=getattr(user,"email_digest_enabled",False),
                ai_active_count=ai_count,
                footer_enabled=getattr(user,"footer_enabled",True),
                channel_set=bool(user.channel_forward_id),
                fetch_interval=getattr(user,"fetch_interval_minutes",30)))

    elif action=="help":
        t1="راهنما" if fa else "Help"
        await query.edit_message_text(f"❓ <b>{t1}</b>",parse_mode=ParseMode.HTML,
            reply_markup=help_menu(lang,plan))

    elif action=="bookmarks":
        from bot.handlers.bookmarks import show_bookmarks
        await show_bookmarks(update,context,user)

    elif action in ("toggle_footer","pause","channel","export"):
        await _legacy_action(query,user,action,lang,parts)


async def _legacy_action(query,user,action,lang,parts):
    fa=is_persian(lang)
    async with get_session() as s:
        from sqlalchemy import select
        from bot.models import User as U
        db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
        if not db: return
        if action=="toggle_footer":
            db.footer_enabled=not db.footer_enabled; user.footer_enabled=db.footer_enabled
            msg=("فوتر فعال شد" if db.footer_enabled else "فوتر غیرفعال") if fa else \
                ("Footer enabled" if db.footer_enabled else "Footer disabled")
            await query.answer(msg)
        elif action=="export":
            fmt=parts[2] if len(parts)>2 and parts[2] in("csv","json") else "csv"
            await _handle_export(query,user,fmt)
        elif action=="channel":
            await _show_channel_settings(query,user)


# ── SETTINGS CALLBACK ─────────────────────────────────────────────────────────

async def cb_settings(update, context):
    query=update.callback_query
    user=context.user_data.get("user")
    if not user:
        await query.answer(); return
    lang=user.language; fa=is_persian(lang); plan=_plan_str(user)
    parts=query.data.split(":"); action=parts[1] if len(parts)>1 else ""

    if action=="locked":
        await query.answer()
        t1="برای فعال‌سازی این ویژگی به Premium نیاز دارید!" if fa else "Upgrade to Premium to unlock this feature!"
        await query.edit_message_text(f"⭐️ {t1}",parse_mode=ParseMode.HTML,
            reply_markup=settings_locked_upgrade(lang))

    elif action=="language":
        await query.answer()
        from bot.utils.keyboards import language_keyboard
        t1="زبان مورد نظر را انتخاب کنید:" if fa else "Select your language:"
        await query.edit_message_text(f"🌐 {t1}",reply_markup=language_keyboard())

    elif action=="ai":
        await query.answer()
        t1="ویژگی‌های AI" if fa else "AI Features"
        await query.edit_message_text(f"🤖 <b>{t1}</b>",parse_mode=ParseMode.HTML,
            reply_markup=ai_features_menu(lang,user.ai_summarize,user.ai_translate,
                user.ai_categorize,user.ai_spam_tag,
                translate_lang=user.ai_translate_lang or "fa"))

    elif action=="export":
        await query.answer()
        if plan not in("pro","premium"):
            await query.edit_message_text("🔒 Export requires Pro or Premium.",
                reply_markup=settings_locked_upgrade(lang)); return
        fmt_arg = parts[2] if len(parts)>2 else None
        if fmt_arg in ("csv","json"):
            await _handle_export(query,user,fmt_arg)
        elif plan=="premium":
            from telegram import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
            kb=IKM([
                [IKB("📄 CSV",callback_data="settings:export:csv"), IKB("🧾 JSON",callback_data="settings:export:json")],
                [IKB("↩️ "+("بازگشت" if fa else "Back"),callback_data="profile:settings")],
            ])
            t1="فرمت خروجی را انتخاب کنید:" if fa else "Choose export format:"
            await query.edit_message_text(f"📤 {t1}",reply_markup=kb)
        else:
            await _handle_export(query,user,"csv")

    elif action=="fetchinterval":
        await query.answer()
        from bot.utils.keyboards import fetch_interval_keyboard
        t1="بازه دریافت پست جدید" if fa else "New Post Fetch Interval"
        t2="هر چند دقیقه یکبار پست‌های جدید بررسی شود؟" if fa else "How often should we check for new posts?"
        await query.edit_message_text(f"⏱ <b>{t1}</b>\n\n{t2}",parse_mode=ParseMode.HTML,
            reply_markup=fetch_interval_keyboard(lang, getattr(user,"fetch_interval_minutes",30)))

    elif action=="fetchint":
        minutes=int(parts[2]) if len(parts)>2 and parts[2] in("10","30","60") else 30
        if plan!="premium":
            await query.answer("Premium only.", show_alert=True); return
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import User as U
            db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db: db.fetch_interval_minutes=minutes; user.fetch_interval_minutes=minutes
        from bot.utils.keyboards import fetch_interval_keyboard
        t1=f"✅ بازه دریافت روی {minutes} دقیقه تنظیم شد." if fa else f"✅ Fetch interval set to {minutes} minutes."
        await query.answer(t1, show_alert=True)
        await query.edit_message_reply_markup(reply_markup=fetch_interval_keyboard(lang, minutes))

    elif action=="toggle":
        field=parts[2] if len(parts)>2 else ""

        # Issue 3: Email Digest needs an email on file before it can be enabled
        if field=="digest" and not getattr(user,"email_digest_enabled",False) and not getattr(user,"email",None):
            await query.answer()
            t1="برای فعال‌سازی دایجست ایمیل، ابتدا آدرس ایمیل خود را وارد کنید:" if fa else \
               "To enable Email Digest, please enter your email address first:"
            await query.edit_message_text(f"📧 {t1}")
            context.user_data["waiting_for"]="email_for_digest"
            return

        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import User as U
            db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if not db:
                await query.answer(); return
            if field=="spam":
                db.hide_spam_posts=not db.hide_spam_posts; user.hide_spam_posts=db.hide_spam_posts
                await query.answer()
            elif field=="digest":
                db.email_digest_enabled=not db.email_digest_enabled
                user.email_digest_enabled=db.email_digest_enabled
                await query.answer()
            elif field=="footer":
                db.footer_enabled=not db.footer_enabled; user.footer_enabled=db.footer_enabled
                # Issue 6: explain what this toggle actually does — users were confused
                if db.footer_enabled:
                    t1=("فوتر تبلیغاتی ربات هر چند پست یکبار به پیام‌های شما اضافه می‌شود." if fa
                        else "A small bot signature will be added to your posts every few messages.")
                else:
                    t1=("فوتر تبلیغاتی حذف شد — پست‌های شما تمیز و بدون برند ربات خواهند بود." if fa
                        else "Bot signature removed — your posts will be clean with no branding.")
                await query.answer(t1, show_alert=True)
            else:
                await query.answer()
        ai_count=sum([user.ai_summarize,user.ai_translate,user.ai_categorize,user.ai_spam_tag])
        try:
            await query.edit_message_reply_markup(reply_markup=settings_menu(lang,plan,
                spam_filter=getattr(user,"hide_spam_posts",False),
                email_digest=getattr(user,"email_digest_enabled",False),
                ai_active_count=ai_count,
                footer_enabled=getattr(user,"footer_enabled",True),
                channel_set=bool(user.channel_forward_id),
                fetch_interval=getattr(user,"fetch_interval_minutes",30)))
        except Exception: pass

    elif action=="channel":
        await query.answer()
        await _show_channel_settings(query,user)

    else:
        await query.answer()


# ── AI CALLBACK ───────────────────────────────────────────────────────────────

async def cb_ai(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; parts=query.data.split(":"); action=parts[1] if len(parts)>1 else ""

    if action=="toggle":
        field=parts[2] if len(parts)>2 else ""
        col={"summarize":"ai_summarize","translate":"ai_translate",
             "categorize":"ai_categorize","spam_tag":"ai_spam_tag"}.get(field)
        if col:
            async with get_session() as s:
                from sqlalchemy import select
                from bot.models import User as U
                db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
                if db:
                                    setattr(db,col,not getattr(db,col)); setattr(user,col,getattr(db,col))
                                    await s.commit()
        await query.edit_message_reply_markup(reply_markup=ai_features_menu(
            lang,user.ai_summarize,user.ai_translate,user.ai_categorize,user.ai_spam_tag,
            translate_lang=user.ai_translate_lang or "fa"))

    elif action=="enable_all":
        from sqlalchemy import select
        from bot.models import User as U
        async with get_session() as s:
            db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db:
                db.ai_summarize=db.ai_translate=db.ai_categorize=db.ai_spam_tag=True
                user.ai_summarize=user.ai_translate=user.ai_categorize=user.ai_spam_tag=True
                await s.commit()
        await query.edit_message_reply_markup(reply_markup=ai_features_menu(
            lang,True,True,True,True,translate_lang=user.ai_translate_lang or "fa"))

    elif action=="disable_all":
        from sqlalchemy import select
        from bot.models import User as U
        async with get_session() as s:
            db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db:
                db.ai_summarize=db.ai_translate=db.ai_categorize=db.ai_spam_tag=False
                user.ai_summarize=user.ai_translate=user.ai_categorize=user.ai_spam_tag=False
                await s.commit()
        await query.edit_message_reply_markup(reply_markup=ai_features_menu(
            lang,False,False,False,False,translate_lang=user.ai_translate_lang or "fa"))

    elif action=="translate":
        if len(parts)>2 and parts[2]=="settings":
            await query.edit_message_text("🤖 AI Translate",
                reply_markup=ai_translate_menu(lang,user.ai_translate_lang or "fa"))

    elif action=="setlang":
        code=parts[2] if len(parts)>2 else "en"
        fa=is_persian(lang)
        if code=="custom":
            from bot.utils.keyboards import back_button
            t1="نام زبان مقصد را تایپ کنید (می‌توانید با کیبورد خودتان هم تایپ کنید):" if fa else \
               "Type the target language name (you can type in your own language too):"
            await query.edit_message_text(f"✏️ {t1}", reply_markup=back_button(lang,"settings:ai"))
            context.user_data["waiting_for"]="ai_translate_lang"; return
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import User as U
            db=(await s.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db:
                db.ai_translate_lang=code
                db.ai_translate=True  # selecting a language activates the feature
                user.ai_translate_lang=code
                user.ai_translate=True
        # Issue 4 fix: query.answer() was already called at the top of cb_ai —
        # Telegram rejects a second answer() call on the same callback query.
        # Show the confirmation by editing the message text instead.
        lang_names={"en":"English","es":"Español","fr":"Français","de":"Deutsch",
                    "ar":"العربية","fa":"فارسی","zh":"中文","ja":"日本語"}
        display=lang_names.get(code,code)
        t3="✅ ترجمه فعال شد" if fa else "✅ AI Translate is now enabled"
        t2=f"✅ زبان ترجمه روی «{display}» تنظیم شد.\n{t3}." if fa else f"✅ Translation language set to \"{display}\".\n{t3}."
        await query.edit_message_text(f"🤖 AI Features\n\n{t2}",
            reply_markup=ai_features_menu(lang,user.ai_summarize,True,user.ai_categorize,user.ai_spam_tag,
                                          translate_lang=code))


# ── SUB / HELP CALLBACKS ──────────────────────────────────────────────────────

async def cb_sub(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; fa=is_persian(lang); action=query.data.split(":")[1]
    plan=_plan_str(user)

    if action=="compare":
        if fa:
            txt=(
                "📊 <b>مقایسه کامل پلن‌ها</b>\n\n"
                "<b>🆓 رایگان</b>\n"
                "▫️ ۵ اکانت از ۵ پلتفرم پایه (یوتیوب، توییتر، RSS، ردیت، تلگرام)\n"
                "▫️ ۱ تیکت پشتیبانی همزمان\n"
                "▫️ بوک‌مارک نامحدود\n\n"
                "<b>⭐️ Pro</b>\n"
                "▫️ ۴۰ اکانت + ۵ پلتفرم اضافه (اینستاگرام، لینکدین، Threads، Bluesky، Mastodon)\n"
                "▫️ ۲ تیکت همزمان\n"
                "▫️ خروجی گرفتن از لیست اکانت‌ها (CSV)\n"
                "▫️ دانلود لینک مستقیم ویدیو*\n\n"
                "<b>💎 Premium</b>\n"
                "▫️ ۱۰۰ اکانت + دسترسی به هر ۱۳ پلتفرم (شامل تیک‌تاک، فیسبوک، دیسکورد)\n"
                "▫️ ۳ تیکت همزمان + چت مستقیم با هوش مصنوعی\n"
                "▫️ خروجی CSV و JSON\n"
                "▫️ دانلود لینک و فایل ویدیو + استخراج صدا*\n"
                "▫️ 🤖 خلاصه‌سازی خودکار پست‌ها با AI\n"
                "▫️ 🌐 ترجمه خودکار پست‌ها به زبان دلخواه (۳۳۰+ زبان)\n"
                "▫️ 🚫 فیلتر هوشمند اسپم\n"
                "▫️ 📧 دایجست ایمیلی روزانه\n"
                "▫️ 📺 فوروارد خودکار به کانال شخصی\n"
                "▫️ ⏱ انتخاب بازه دریافت پست (۱۰/۳۰/۶۰ دقیقه)\n"
                "▫️ حذف امضای تبلیغاتی ربات از پست‌ها\n\n"
                "<i>* در دسترس بودن دانلود ویدیو به پلتفرم مبدا بستگی دارد.</i>"
            )
        else:
            txt=(
                "📊 <b>Full Plan Comparison</b>\n\n"
                "<b>🆓 Free</b>\n"
                "▫️ 5 accounts across 5 core platforms (YouTube, Twitter, RSS, Reddit, Telegram)\n"
                "▫️ 1 support ticket at a time\n"
                "▫️ Unlimited bookmarks\n\n"
                "<b>⭐️ Pro</b>\n"
                "▫️ 40 accounts + 5 more platforms (Instagram, LinkedIn, Threads, Bluesky, Mastodon)\n"
                "▫️ 2 tickets at a time\n"
                "▫️ Export your account list (CSV)\n"
                "▫️ Direct video link downloads*\n\n"
                "<b>💎 Premium</b>\n"
                "▫️ 100 accounts + all 13 platforms (incl. TikTok, Facebook, Discord)\n"
                "▫️ 3 tickets + direct AI chat support\n"
                "▫️ Export as CSV or JSON\n"
                "▫️ Video link + file downloads, audio extraction*\n"
                "▫️ 🤖 Automatic AI post summarization\n"
                "▫️ 🌐 Automatic post translation to your language (330+ languages)\n"
                "▫️ 🚫 Smart spam filtering\n"
                "▫️ 📧 Daily email digest\n"
                "▫️ 📺 Auto-forward posts to your own channel\n"
                "▫️ ⏱ Choose your fetch interval (10/30/60 min)\n"
                "▫️ Remove the bot's promotional signature from posts\n\n"
                "<i>* Video download availability depends on the source platform.</i>"
            )
        await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=compare_plans_keyboard(lang))

    elif action=="history":
        try:
            async with get_session() as s:
                from sqlalchemy import select,func
                from bot.models import Transaction,TransactionStatus
                txs=(await s.execute(
                    select(Transaction).where(Transaction.user_id==user.id,Transaction.status==TransactionStatus.CONFIRMED)
                    .order_by(Transaction.created_at.desc()).limit(10)
                )).scalars().all()
                total=(await s.execute(
                    select(func.sum(Transaction.amount_usd))
                    .where(Transaction.user_id==user.id,Transaction.status==TransactionStatus.CONFIRMED)
                )).scalar() or 0
            if not txs:
                t1="تاریخچه‌ای وجود ندارد." if fa else "No payment history found."
                txt=f"📋 {t1}"
            else:
                rows="\n".join(f"• {tx.created_at.strftime('%Y-%m-%d')} — ${tx.amount_usd:.0f} — {tx.plan}" for tx in txs)
                t1="تاریخچه پرداخت" if fa else "Payment History"
                t2="مجموع" if fa else "Total"
                txt=f"📋 <b>{t1}</b>\n\n{rows}\n\n{t2}: <b>${total:.0f}</b>"
        except Exception:
            t1="خطا در دریافت تاریخچه." if fa else "Could not load history."
            txt=f"📋 {t1}"
        await query.edit_message_text(txt,parse_mode=ParseMode.HTML,
            reply_markup=back_button(lang,"profile:subscription"))


async def cb_help(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; fa=is_persian(lang); plan=_plan_str(user)
    action=query.data.split(":")[1] if ":" in query.data else ""

    if action=="faq":
        if fa:
            txt=(
                "📖 <b>سوالات متداول</b>\n\n"
                "<b>📱 حساب‌ها</b>\n"
                "▫️ چطور اکانت اضافه کنم؟\n"
                "📋 اکانت‌ها ← ➕ افزودن جدید ← پلتفرم را انتخاب کنید ← لینک یا نام کاربری را بفرستید.\n\n"
                "▫️ چرا نمی‌توانم فلان پلتفرم را اضافه کنم؟\n"
                "برخی پلتفرم‌ها فقط برای پلن Pro یا Premium باز هستند. جزئیات را در «مقایسه پلن‌ها» ببینید.\n\n"
                "▫️ چطور یک اکانت را حذف یا متوقف کنم؟\n"
                "روی پلتفرم مربوطه بزنید، سپس ⏸ توقف یا 🗑️ حذف را انتخاب کنید.\n\n"
                "<b>💳 اشتراک و پرداخت</b>\n"
                "▫️ چطور پلن را ارتقا دهم؟\n"
                "👤 پروفایل ← 💳 اشتراک ← ⭐️/💎 ارتقا ← دوره پرداخت را انتخاب کنید.\n\n"
                "▫️ پرداخت با چه روشی انجام می‌شود؟\n"
                "در حال حاضر فقط کریپتو (USDT). سایر روش‌ها به‌زودی اضافه می‌شوند.\n\n"
                "▫️ اگر پرداختم تایید نشد چه کنم؟\n"
                "چند دقیقه صبر کنید؛ تراکنش‌های بلاکچین گاهی کمی طول می‌کشند. اگر بعد از ۳۰ دقیقه هنوز تایید نشد، تیکت باز کنید.\n\n"
                "<b>🤖 هوش مصنوعی (Premium)</b>\n"
                "▫️ AI Translate چطور کار می‌کند؟\n"
                "پست‌ها به زبان انتخابی شما به‌صورت خودکار ترجمه می‌شوند. زبان را از ⚙️ تنظیمات ← 🤖 AI تغییر دهید.\n\n"
                "<b>📤 دعوت از دوستان</b>\n"
                "▫️ رفرال چطور کار می‌کند؟\n"
                "لینک خود را به اشتراک بگذارید. برای هر دوست، ۲ امتیاز و هر ۵ دوست، ۱۰ امتیاز جایزه می‌گیرید.\n\n"
                "❓ سوال دیگری دارید؟ یک تیکت باز کنید."
            )
        else:
            txt=(
                "📖 <b>Frequently Asked Questions</b>\n\n"
                "<b>📱 Accounts</b>\n"
                "▫️ How do I add an account?\n"
                "📋 Accounts → ➕ Add New → pick a platform → send the link or username.\n\n"
                "▫️ Why can't I add a certain platform?\n"
                "Some platforms require Pro or Premium. Check 📊 Compare Plans for details.\n\n"
                "▫️ How do I delete or pause an account?\n"
                "Open the platform, then tap ⏸ Pause or 🗑️ Delete.\n\n"
                "<b>💳 Subscription & Payment</b>\n"
                "▫️ How do I upgrade my plan?\n"
                "👤 Profile → 💳 Subscription → ⭐️/💎 Upgrade → choose your billing period.\n\n"
                "▫️ What payment methods are supported?\n"
                "Currently Crypto (USDT) only. More methods are coming soon.\n\n"
                "▫️ My payment wasn't confirmed — what now?\n"
                "Blockchain transactions can take a few minutes. If it's still pending after 30 minutes, open a ticket.\n\n"
                "<b>🤖 AI Features (Premium)</b>\n"
                "▫️ How does AI Translate work?\n"
                "Posts are automatically translated to your chosen language. Change it in ⚙️ Settings → 🤖 AI Features.\n\n"
                "<b>📤 Referrals</b>\n"
                "▫️ How does the referral program work?\n"
                "Share your link — earn 2 points per friend, plus a 10-point bonus every 5 friends.\n\n"
                "❓ Still have questions? Open a ticket below."
            )
        await query.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=back_button(lang,"profile:help"))

    elif action=="tickets":
        from bot.handlers.support import show_my_tickets
        await show_my_tickets(update,context,user)

    elif action=="new_ticket":
        t1="تیکت جدید" if fa else "New Ticket"
        t2="موضوع تیکت را انتخاب کنید:" if fa else "Select a subject:"
        await query.edit_message_text(f"➕ <b>{t1}</b>\n\n{t2}",parse_mode=ParseMode.HTML,
            reply_markup=ticket_subjects(lang))

    elif action=="ai_chat":
        if plan!="premium":
            t1="چت AI فقط برای Premium است." if fa else "AI Chat is Premium only."
            await query.edit_message_text(f"🔒 {t1}",reply_markup=ai_chat_locked_keyboard(lang)); return
        t1="چت هوش مصنوعی" if fa else "AI Chat"
        t2="سوال خود را تایپ کنید:" if fa else "Type your question:"
        await query.edit_message_text(f"🤖 <b>{t1}</b>\n\n{t2}",parse_mode=ParseMode.HTML)
        context.user_data["waiting_for"]="ai_chat"

    elif action=="ai_chat_locked":
        t1="چت AI فقط برای Premium است." if fa else "AI Chat is Premium only."
        await query.edit_message_text(f"🔒 {t1}",reply_markup=ai_chat_locked_keyboard(lang))

    elif action=="contact":
        from bot.utils.keyboards import contact_support_keyboard
        t1="یا مستقیم ایمیل بزنید:" if fa else "Or email us directly:"
        t2="یا یک تیکت باز کنید:" if fa else "Or open a support ticket:"
        await query.edit_message_text(
            f"📧 <b>{'تماس با پشتیبانی' if fa else 'Contact Support'}</b>\n\n"
            f"{t1}\n<code>aisocialfeed@gmail.com</code>\n\n{t2}",
            parse_mode=ParseMode.HTML,reply_markup=contact_support_keyboard(lang))


# ── EXPORT / CHANNEL / DIGEST (preserved) ────────────────────────────────────

async def _handle_export(query, user, fmt):
    lang=user.language; fa=is_persian(lang)
    try:
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import Account
            accs=(await s.execute(select(Account).where(Account.user_id==user.id))).scalars().all()
        if fmt=="json":
            import json
            data=json.dumps([{"platform":a.platform.value,"identifier":a.identifier,
                              "display_name":a.display_name,"active":a.is_active} for a in accs],
                            ensure_ascii=False,indent=2)
            fname="accounts.json"
        else:
            rows=["platform,identifier,display_name,active"]
            rows+=[f"{a.platform.value},{a.identifier},{a.display_name},{a.is_active}" for a in accs]
            data="\n".join(rows); fname="accounts.csv"

        # Issue 12: send as a real downloadable file, not a text dump
        import io
        file_bytes = io.BytesIO(data.encode("utf-8"))
        file_bytes.name = fname
        t1="فایل خروجی شما آماده است." if fa else "Your export file is ready."
        await query.message.chat.send_document(
            document=file_bytes, filename=fname,
            caption=f"📤 {t1}",
        )
        await query.answer()
    except Exception as e:
        await query.edit_message_text(f"❌ Export failed: {e}",reply_markup=back_button(lang,"profile:settings"))


async def _show_channel_settings(query, user):
    lang=user.language; fa=is_persian(lang)
    current=user.channel_forward_id or ""
    t1="فوروارد به کانال" if fa else "Channel Forward"
    t2="آی‌دی کانال فعلی:" if fa else "Current channel ID:"
    t3="شناسه کانال را ارسال کنید" if fa else "Send the channel ID"
    txt=f"📺 <b>{t1}</b>\n\n{t2} <code>{current}</code>\n\n{t3}:"
    await query.edit_message_text(txt,parse_mode="HTML",reply_markup=back_button(lang,"profile:settings"))
    query._context.user_data["waiting_for"]="channel_id" if hasattr(query,"_context") else None


async def show_stats(update, context, user):
    lang=user.language; fa=is_persian(lang)
    try:
        async with get_session() as s:
            from sqlalchemy import select,func
            from bot.models import Account, SentPost
            acc_count=(await s.execute(select(func.count()).select_from(Account).where(Account.user_id==user.id))).scalar() or 0
            post_count=(await s.execute(select(func.count()).select_from(SentPost).join(Account,SentPost.account_id==Account.id).where(Account.user_id==user.id))).scalar() or 0
        t1="آمار" if fa else "Stats"
        t2="اکانت‌های فعال" if fa else "Active accounts"
        t3="کل پست‌ها" if fa else "Total posts"
        txt=f"📊 <b>{t1}</b>\n\n{t2}: <b>{acc_count}</b>\n{t3}: <b>{post_count}</b>"
    except Exception:
        txt="📊 Stats unavailable"
    await safe_send_message(update.effective_user.id,txt,parse_mode=ParseMode.HTML,
        reply_markup=back_button(lang,"menu:main"))


async def show_daily_summary(update, context, user):
    lang=user.language; fa=is_persian(lang)
    t1="خلاصه روزانه در حال توسعه است." if fa else "Daily summary coming soon."
    await safe_send_message(update.effective_user.id,f"📅 {t1}")


async def cb_digest(update, context):
    query=update.callback_query; await query.answer()
    user=context.user_data.get("user")
    if not user: return
    lang=user.language; fa=is_persian(lang)
    await query.edit_message_text(
        "📧 "+("تنظیمات دایجست در حال توسعه." if fa else "Digest settings coming soon."),
        reply_markup=back_button(lang,"profile:settings"))


# ── REGISTER ──────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(cb_profile,  pattern=r"^profile:"))
    app.add_handler(CallbackQueryHandler(cb_ai,       pattern=r"^ai:"))
    app.add_handler(CallbackQueryHandler(cb_settings, pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(cb_sub,      pattern=r"^sub:"))
    app.add_handler(CallbackQueryHandler(cb_help,     pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(cb_digest,   pattern=r"^digest:"))
    from bot.handlers.referral import cb_referral
    app.add_handler(CallbackQueryHandler(cb_referral, pattern=r"^referral:"))
    logger.info("Profile handlers registered v4.2")
