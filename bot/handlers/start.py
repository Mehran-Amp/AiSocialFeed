from __future__ import annotations
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from bot.database import get_session
from bot.middlewares.auth import auth_middleware
from bot.models import User, PlanType
from bot.utils.fixes import cmd_cancel
from bot.utils.keyboards import language_keyboard, main_menu
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t, SUPPORTED_LANGUAGES, get_language_name
from config.settings import config
logger = logging.getLogger(__name__)


def _is_admin(tg_id: int) -> bool:
    return tg_id == config.telegram.admin_id


async def _handle_referral_args(update: Update, lang: str, user: User, args: list[str]) -> None:
    from bot.handlers.referral import handle_referral_safe
    credited = await handle_referral_safe(user.id, args[0][4:])
    if credited:
        f = lang == "fa"
        await safe_send_message(
            update.effective_user.id,
            "🎁 " + ("خوش آمدید! دوستتان یک امتیاز کسب کرد." if f
                     else "Welcome! Your referral bonus was applied."),
        )


async def _handle_admin_user_deep_link(update: Update, args: list[str]) -> bool:
    uid = int(args[0].split("_")[1])
    from bot.database import get_session
    from bot.models import User as UserModel
    from bot.utils.keyboards import admin_user_actions
    from sqlalchemy import select
    async with get_session() as session:
        u = (await session.execute(
            select(UserModel).where(UserModel.id == uid)
        )).scalar_one_or_none()
        if u:
            plan      = u.plan.value if hasattr(u.plan, "value") else str(u.plan)
            expires   = u.subscription_expires_at.strftime("%Y-%m-%d") if u.subscription_expires_at else "—"
            is_banned = getattr(u, "is_banned", False)
            await update.message.reply_text(
                f"👤 <b>User Detail</b>\n\nID: <code>{uid}</code>\n"
                f"Plan: <b>{plan}</b>\nExpires: {expires}",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_user_actions(uid, is_banned),
            )
            return True
    return False


@auth_middleware
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user: User = context.user_data["user"]
    lang = user.language
    args = context.args or []

    if args and args[0].startswith("ref_"):
        await _handle_referral_args(update, lang, user, args)

    # Deep-link from Django Admin "Open in TG" button — only for admin
    if args and args[0].startswith("adminuser_") and _is_admin(update.effective_user.id):
        handled = await _handle_admin_user_deep_link(update, args)
        if handled:
            return

    is_new = (
        user.created_at is not None
        and (datetime.now(timezone.utc) - user.created_at).total_seconds() < 60
    )
    admin = _is_admin(update.effective_user.id)
    context.user_data["is_admin"] = admin  # Req #15: persist for all keyboards
    plan_str = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    if is_new:
        await update.message.reply_text(
            t("welcome.first_time", lang), parse_mode=ParseMode.HTML,
            reply_markup=language_keyboard(),
        )
    else:
        name = update.effective_user.first_name or "there"
        await update.message.reply_text(
            t("welcome.returning", lang, name=name),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(lang, plan_str, admin, 0),
        )


async def cb_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split(":")[1]
    if lang_code not in SUPPORTED_LANGUAGES:
        return
    tg_user = update.effective_user
    async with get_session() as session:
        from sqlalchemy import select
        from bot.models import User as UserModel
        user = (await session.execute(select(UserModel).where(UserModel.telegram_id == tg_user.id))).scalar_one_or_none()
        if user:
            user.language = lang_code
    if "user" in context.user_data:
        context.user_data["user"].language = lang_code
    await query.edit_message_text(f"✅ Language set to <b>{get_language_name(lang_code)}</b>", parse_mode=ParseMode.HTML)
    admin = _is_admin(tg_user.id)
    await safe_send_message(
        tg_user.id,
        t("welcome.returning", lang_code, name=tg_user.first_name or "there"),
        reply_markup=main_menu(lang_code, "free", admin, 0),
    )


@auth_middleware
async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user: User = context.user_data["user"]
    from bot.handlers.referral import show_referral
    await show_referral(update, context, user)


@auth_middleware
async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user: User = context.user_data["user"]
    from bot.handlers.payment import show_plans
    await show_plans(update, context, user)


@auth_middleware
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user: User = context.user_data["user"]
    lang = user.language
    fa = lang == "fa"
    text = update.message.text

    # ── Issue 6: waiting_for text-input capture — MUST run before button routing ──
    waiting_for = context.user_data.get("waiting_for")
    if waiting_for:
        handled = await _handle_waiting_for(update, context, user, waiting_for, text)
        if handled:
            return

    # Admin Panel button
    if text == "⚙️ Admin Panel":
        if _is_admin(update.effective_user.id):
            context.user_data["is_admin"] = True
            from bot.handlers.admin_tg import show_admin_menu
            await show_admin_menu(update, context)
        return

    # ── v4.2: 3-button main menu + accounts submenu ─────────────────────────
    updates_label   = "🔄 " + ("بروزرسانی" if fa else "Updates")
    my_accounts_lbl = "📋 " + ("اکانت‌های من" if fa else "My Accounts")
    add_new_lbl     = "➕ " + ("افزودن جدید" if fa else "Add New")
    back_lbl        = "↩️ " + ("بازگشت" if fa else "Back")
    profile_lbl     = "👤 " + ("پروفایل" if fa else "Profile")

    # Accounts button on main menu is dynamic: "📋 Accounts (N)" or "➕ Account"
    is_accounts_btn = text.startswith("📋 ") or text.startswith("➕ ")

    if text == updates_label:
        if user.plan == PlanType.FREE:
            msg = "🔒 این گزینه فقط برای کاربران Pro و Premium فعال است." if fa else "🔒 This option is only enabled for Pro and Premium users."
            await update.message.reply_text(msg)
            from bot.handlers.payment import show_plans
            await show_plans(update, context, user)
        else:
            from bot.handlers.accounts import handle_updates
            await handle_updates(update, context, user)
        return

    if text == profile_lbl:
        from bot.handlers.profile import show_profile
        await show_profile(update, context, user)
        return

    if text == my_accounts_lbl:
        from bot.handlers.accounts import show_platform_list
        await show_platform_list(update, context, user)
        return

    if text == add_new_lbl:
        from bot.handlers.accounts import show_platform_selection
        await show_platform_selection(update, context, user)
        return

    if text == back_lbl:
        await _route_main_menu(update, context, user)
        return

    if is_accounts_btn and not (text == my_accounts_lbl or text == add_new_lbl):
        # Main menu accounts button (with count or "Add Account")
        from bot.handlers.accounts import show_accounts_submenu
        await show_accounts_submenu(update, context, user)
        return


# ── Issue 6: language name recognition (curated + free text fallback) ────────
_LANGUAGE_NAME_MAP = {
    "english":"en","انگلیسی":"en","انگلیسیfa":"en",
    "farsi":"fa","persian":"fa","فارسی":"fa",
    "spanish":"es","español":"es","اسپانیایی":"es",
    "french":"fr","français":"fr","فرانسوی":"fr",
    "german":"de","deutsch":"de","آلمانی":"de",
    "arabic":"ar","العربية":"ar","عربی":"ar",
    "chinese":"zh","中文":"zh","چینی":"zh",
    "japanese":"ja","日本語":"ja","ژاپنی":"ja",
    "russian":"ru","русский":"ru","روسی":"ru",
    "turkish":"tr","türkçe":"tr","ترکی":"tr",
    "portuguese":"pt","português":"pt","پرتغالی":"pt",
    "italian":"it","italiano":"it","ایتالیایی":"it",
    "korean":"ko","한국어":"ko","کره‌ای":"ko",
    "hindi":"hi","हिन्दी":"hi","هندی":"hi",
    "urdu":"ur","اردو":"ur",
    "bengali":"bn","বাংলা":"bn","بنگالی":"bn",
    "indonesian":"id","bahasa":"id","اندونزیایی":"id",
    "vietnamese":"vi","tiếng việt":"vi","ویتنامی":"vi",
    "thai":"th","ไทย":"th","تایلندی":"th",
    "kurdish":"ku","kurdî":"ku","کردی":"ku",
    "dutch":"nl","nederlands":"nl","هلندی":"nl",
    "polish":"pl","polski":"pl","لهستانی":"pl",
    "ukrainian":"uk","українська":"uk","اوکراینی":"uk",
    "hebrew":"he","עברית":"he","عبری":"he",
    "greek":"el","ελληνικά":"el","یونانی":"el",
    "swedish":"sv","svenska":"sv","سوئدی":"sv",
}


def _resolve_language_name(raw: str) -> tuple[str, str]:
    """
    Returns (iso_code, display_name).
    Matches curated list case/diacritic-insensitively; falls back to
    storing the raw typed text as a custom label if no match found.
    """
    stripped = raw.strip()
    key = stripped.lower()
    if key in _LANGUAGE_NAME_MAP:
        return _LANGUAGE_NAME_MAP[key], stripped
    return stripped[:10], stripped  # unmatched: store raw text as both code+label (issue-6 fallback)


async def _handle_waiting_for(update, context, user, waiting_for, text) -> bool:
    """
    Issue 6: catches free-text replies for AI Translate custom language,
    AI Chat questions, and Channel ID input. Always clears waiting_for
    and always shows a confirmation + Back button.
    """
    lang = user.language
    fa = lang == "fa"
    context.user_data.pop("waiting_for", None)

    if waiting_for == "ai_translate_lang":
        code, display = _resolve_language_name(text)
        from bot.database import get_session
        from bot.utils.keyboards import ai_features_menu
        async with get_session() as s:
            from sqlalchemy import select
            db = (await s.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if db:
                db.ai_translate_lang = code
                db.ai_translate = True  # selecting a language activates the feature
                user.ai_translate_lang = code
                user.ai_translate = True
        t3 = "✅ ترجمه فعال شد" if fa else "✅ AI Translate is now enabled"
        t1 = f"✅ زبان ترجمه روی «{display}» تنظیم شد.\n{t3}." if fa else f"✅ Translation language set to \"{display}\".\n{t3}."
        await update.message.reply_text(f"🤖 AI Features\n\n{t1}",
            reply_markup=ai_features_menu(lang,user.ai_summarize,True,user.ai_categorize,user.ai_spam_tag,
                                          translate_lang=code))
        return True

    if waiting_for == "ai_chat":
        from bot.utils.keyboards import back_button
        if user.plan != PlanType.PREMIUM:
            t1 = "این ویژگی فقط برای Premium است." if fa else "This feature is Premium only."
            await update.message.reply_text(f"🔒 {t1}", reply_markup=back_button(lang, "profile:help"))
            return True
        try:
            from bot.services.ai_service import AIService
            svc = AIService()
            answer = await svc.answer_question(text, lang=lang)
        except Exception:
            answer = ("متأسفم، در حال حاضر نمی‌توانم پاسخ دهم." if fa
                      else "Sorry, I couldn't process that right now.")
        await update.message.reply_text(f"🤖 {answer}", reply_markup=back_button(lang, "profile:help"))
        return True

    if waiting_for == "email_for_digest":
        import re as _re
        from bot.database import get_session
        from bot.utils.keyboards import back_button
        email = text.strip()
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            t1 = "آدرس ایمیل معتبر نیست. دوباره تلاش کنید یا بازگردید." if fa else \
                 "That doesn't look like a valid email. Try again or go back."
            await update.message.reply_text(f"❌ {t1}", reply_markup=back_button(lang, "profile:settings"))
            context.user_data["waiting_for"] = "email_for_digest"  # let them retry
            return True
        async with get_session() as s:
            from sqlalchemy import select
            db = (await s.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if db:
                db.email = email
                db.email_digest_enabled = True
                user.email = email
                user.email_digest_enabled = True
        t1 = f"✅ ایمیل ثبت شد و دایجست ایمیل فعال شد." if fa else \
             f"✅ Email saved and Email Digest enabled."
        await update.message.reply_text(t1, reply_markup=back_button(lang, "profile:settings"))
        return True

    if waiting_for == "channel_id":
        from bot.database import get_session
        from bot.utils.keyboards import back_button
        try:
            channel_id = int(text.strip())
        except ValueError:
            t1 = "شناسه کانال باید عدد باشد. دوباره تلاش کنید یا بازگردید." if fa else \
                 "Channel ID must be a number. Try again or go back."
            await update.message.reply_text(f"❌ {t1}", reply_markup=back_button(lang, "profile:settings"))
            return True
        async with get_session() as s:
            from sqlalchemy import select
            db = (await s.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if db:
                db.channel_forward_id = channel_id
                user.channel_forward_id = channel_id
        t1 = "✅ کانال با موفقیت تنظیم شد." if fa else "✅ Channel forward set successfully."
        await update.message.reply_text(t1, reply_markup=back_button(lang, "profile:settings"))
        return True

    return False


async def _route_main_menu(update, context, user):
    plan_str = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    is_adm = context.user_data.get("is_admin", False)
    from bot.utils.keyboards import main_menu
    from bot.database import get_session
    async with get_session() as s:
        from sqlalchemy import select, func
        from bot.models import Account
        count = (await s.execute(
            select(func.count()).select_from(Account).where(Account.user_id == user.id)
        )).scalar() or 0
    await update.message.reply_text(
        "🏠", reply_markup=main_menu(user.language, plan_str, is_adm, count)
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(CommandHandler("referral", cmd_referral))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CallbackQueryHandler(cb_set_language, pattern=r"^setlang:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    logger.info("Start handlers registered.")
