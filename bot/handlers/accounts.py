"""SocialtoFeed — Accounts Handler v4.2"""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)
from telegram import ReplyKeyboardRemove
from bot.database import get_session
from bot.models import Account, Category, Platform, PlanType, User, SentPost
from bot.utils.keyboards import (
    accounts_submenu, add_account_button, back_button,
    confirm_delete_account, error_account_keyboard, error_with_home,
    locked_platform_upgrade, main_menu,
    platform_detail_keyboard, platform_keyboard,
    platform_list_keyboard, post_buttons,
    FREE_PLATFORMS, PRO_PLATFORMS, PREMIUM_PLATFORMS, PLATFORM_EMOJI,
)
from bot.utils.telegram_utils import safe_send_message, safe_edit
from bot.utils.translator import t

logger = logging.getLogger(__name__)
WAITING_LINK = 1

PLATFORM_EXAMPLES = {
    "youtube":"youtube.com/c/channelname  OR  @handle",
    "twitter":"twitter.com/username  OR  @username",
    "instagram":"instagram.com/username",
    "rss":"https://example.com/feed.xml",
    "tiktok":"tiktok.com/@username",
    "linkedin":"linkedin.com/company/name",
    "reddit":"reddit.com/r/subreddit",
    "telegram":"t.me/channelname",
    "bluesky":"username.bsky.social",
    "mastodon":"@username@mastodon.social",
    "threads":"@username  OR  threads.net/@username",
    "facebook":"facebook.com/pagename",
    "discord":"discord.com/channels/server-id/channel-id",
}
PLATFORM_LABELS = {
    "youtube":"🎬 YouTube","twitter":"𝕏 Twitter/X","instagram":"📸 Instagram",
    "rss":"📡 RSS","tiktok":"🎵 TikTok","linkedin":"💼 LinkedIn",
    "reddit":"🤖 Reddit","telegram":"✈️ Telegram","bluesky":"🦋 Bluesky",
    "mastodon":"🐘 Mastodon","threads":"🧵 Threads","facebook":"👥 Facebook","discord":"🎮 Discord",
}
ALL_PLATFORM_VALUES = list(FREE_PLATFORMS|PRO_PLATFORMS|PREMIUM_PLATFORMS)

async def _get_last_platform(user_id:int)->Optional[str]:
    try:
        from bot.cache import get_redis
        r=await get_redis()
        return await r.get(f"user:{user_id}:last_platform")
    except Exception: return None

async def _set_last_platform(user_id:int,pv:str)->None:
    try:
        from bot.cache import get_redis
        r=await get_redis()
        await r.set(f"user:{user_id}:last_platform",pv,ex=86400*30)
    except Exception: pass

async def _count_accounts(user_id:int)->int:
    async with get_session() as s:
        from sqlalchemy import select,func
        return (await s.execute(select(func.count()).select_from(Account).where(Account.user_id==user_id))).scalar() or 0

async def _get_plan_cfg(plan):
    async with get_session() as s:
        from sqlalchemy import select
        from bot.models import PlanConfig
        return (await s.execute(select(PlanConfig).where(PlanConfig.plan==plan))).scalar_one_or_none()

def _is_admin(ctx)->bool: return bool(ctx.user_data.get("is_admin",False))
def _plan_str(user:User)->str: return user.plan.value if hasattr(user.plan,"value") else str(user.plan)
def _allowed(plan:str)->set:
    if plan=="premium": return FREE_PLATFORMS|PRO_PLATFORMS|PREMIUM_PLATFORMS
    if plan=="pro":     return FREE_PLATFORMS|PRO_PLATFORMS
    return FREE_PLATFORMS

async def _fetch_recent_posts(user_id:int, since:Optional[datetime], now:datetime) -> list:
    async with get_session() as s:
        from sqlalchemy import select
        q=(select(SentPost, Account.platform).join(Account, SentPost.account_id==Account.id)
           .where(Account.user_id==user_id, Account.is_active==True)
           .order_by(SentPost.published_at.desc()))
        if since: q=q.where(SentPost.published_at>since)
        else:
            from datetime import timedelta
            q=q.where(SentPost.published_at>now-timedelta(hours=24))
        rows=(await s.execute(q.limit(20))).all()
        return [(row[0], row[1]) for row in rows]

async def _update_last_feed_viewed(user_id:int, now:datetime) -> None:
    async with get_session() as s:
        from sqlalchemy import select
        db_user=(await s.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if db_user:
            db_user.last_feed_viewed_at=now
            await s.commit()

async def _trigger_background_fetches(user_id:int) -> None:
    try:
        async with get_session() as s:
            from sqlalchemy import select
            ids=(await s.execute(select(Account.id).where(Account.user_id==user_id,Account.is_active==True))).scalars().all()
        from worker.tasks import fetch_account_task
        for acc_id in ids: fetch_account_task.delay(acc_id)
    except Exception as e: logger.warning(f"[updates] bg fetch failed: {e}")

# ── 🔄 HYBRID UPDATES ─────────────────────────────────────────────────────────
async def handle_updates(update:Update,context:ContextTypes.DEFAULT_TYPE,user:User)->None:
    lang=user.language; f=lang=="fa"; now=datetime.now(timezone.utc)

    posts = await _fetch_recent_posts(user.id, user.last_feed_viewed_at, now)
    await _update_last_feed_viewed(user.id, now)

    if not posts:
        await safe_send_message(update.effective_user.id,"🔄 "+("پست جدیدی یافت نشد." if f else "No new posts found."))
    else:
        await safe_send_message(update.effective_user.id,
            f"🔄 <b>{len(posts)} "+("پست جدید</b>" if f else "new post(s)</b>"),parse_mode=ParseMode.HTML)
        plan=_plan_str(user)
        for post, platform in posts:
            text=f"<b>{post.title or ''}</b>\n{post.url or ''}"
            kb=post_buttons(
                platform=platform.value if platform else "",
                url=post.url or "",url_key=str(post.id),lang=lang,plan=plan)
            await safe_send_message(update.effective_user.id,text,parse_mode=ParseMode.HTML,reply_markup=kb)

    await _trigger_background_fetches(user.id)

# ── ACCOUNTS SUBMENU ──────────────────────────────────────────────────────────
async def show_accounts_submenu(update:Update,context:ContextTypes.DEFAULT_TYPE,user:User)->None:
    lang=user.language; f=lang=="fa"
    count=await _count_accounts(user.id)
    plan=_plan_str(user)
    plan_cfg=await _get_plan_cfg(user.plan)
    from bot.utils.keyboards import PLAN_ACCOUNT_LIMITS
    limit=(plan_cfg.max_accounts if plan_cfg else PLAN_ACCOUNT_LIMITS.get(plan,5))+(user.referral_bonus_accounts or 0)
    header=(f"📋 <b>{'اکانت‌ها' if f else 'Accounts'}</b> ({count}/{limit})\n"
            f"{'پلن' if f else 'Plan'}: {plan.upper()}")
    context.user_data["acc_count"]=count
    await safe_send_message(update.effective_user.id,header,parse_mode=ParseMode.HTML,
                            reply_markup=accounts_submenu(lang,count,is_admin=_is_admin(context)))

# ── MY ACCOUNTS ───────────────────────────────────────────────────────────────
async def show_platform_list(update:Update,context:ContextTypes.DEFAULT_TYPE,user:User)->None:
    lang=user.language; f=lang=="fa"; plan=_plan_str(user)
    allowed=_allowed(plan)
    async with get_session() as s:
        from sqlalchemy import select
        accounts=(await s.execute(select(Account).where(Account.user_id==user.id))).scalars().all()
    counts=defaultdict(int)
    for acc in accounts: counts[acc.platform.value]+=1
    rows=[]
    for pv in ALL_PLATFORM_VALUES:
        try: p=Platform(pv)
        except ValueError: continue
        c=counts.get(pv,0)
        rows.append((p,c,pv in allowed))
    rows.sort(key=lambda x:(0 if x[1]>0 else(1 if x[2] else 2),-x[1]))
    total=sum(counts.values())
    header=f"📋 <b>{'اکانت‌های من' if f else 'My Accounts'}</b> ({total} {'اکانت' if f else 'total'})"
    await safe_send_message(update.effective_user.id,header,parse_mode=ParseMode.HTML,reply_markup=ReplyKeyboardRemove())
    await safe_send_message(update.effective_user.id,
        "↕️ "+("پلتفرم مورد نظر را انتخاب کنید:" if f else "Select a platform:"),
        reply_markup=platform_list_keyboard([(p,c) for p,c,_ in rows],lang))

# ── PLATFORM DETAIL ───────────────────────────────────────────────────────────
async def show_platform_accounts(update:Update,context:ContextTypes.DEFAULT_TYPE,
                                  user:User,platform:Platform,edit_query=None)->None:
    lang=user.language; f=lang=="fa"
    context.user_data["current_platform"]=platform.value
    async with get_session() as s:
        from sqlalchemy import select
        accounts=(await s.execute(
            select(Account).where(Account.user_id==user.id,Account.platform==platform)
            .order_by(Account.is_active.desc(),Account.display_name)
        )).scalars().all()
    plabel=PLATFORM_LABELS.get(platform.value,platform.value.title())
    header=f"{plabel} ({len(accounts)} {'اکانت' if f else 'account(s)'})"
    if edit_query:
        try: await edit_query.edit_message_text(header,parse_mode=ParseMode.HTML)
        except Exception: pass
    else:
        await safe_send_message(update.effective_user.id,header,parse_mode=ParseMode.HTML)
    await safe_send_message(update.effective_user.id,
        "👇 "+("اکانت‌ها:" if f else "Accounts:"),
        reply_markup=platform_detail_keyboard(accounts,platform.value,lang))

# ── ADD NEW ───────────────────────────────────────────────────────────────────
async def show_platform_selection(update:Update,context:ContextTypes.DEFAULT_TYPE,user:User)->None:
    lang=user.language; f=lang=="fa"; plan=_plan_str(user)
    async with get_session() as s:
        from sqlalchemy import select
        accs=(await s.execute(select(Account.platform).where(Account.user_id==user.id))).scalars().all()
    user_platforms={a.value for a in accs}
    last=await _get_last_platform(user.id)
    await safe_send_message(update.effective_user.id,
        "➕ <b>"+("افزودن اکانت جدید" if f else "Add New Account")+"</b>",
        parse_mode=ParseMode.HTML,reply_markup=ReplyKeyboardRemove())
    await safe_send_message(update.effective_user.id,
        "📋 "+("پلتفرم مورد نظر را انتخاب کنید:" if f else "Select a platform:"),
        reply_markup=platform_keyboard(user_plan=plan,user_platforms=user_platforms,last_platform=last,lang=lang))

async def cb_add_account_start(update:Update,context:ContextTypes.DEFAULT_TYPE)->None:
    await update.callback_query.answer()
    user=context.user_data.get("user")
    if user: await show_platform_selection(update,context,user)

async def cb_addacc_noop(update:Update,context:ContextTypes.DEFAULT_TYPE)->None:
    await update.callback_query.answer()

async def cb_platform_selected(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    query=update.callback_query; await query.answer()
    user:Optional[User]=context.user_data.get("user")
    if not user: return ConversationHandler.END
    lang=user.language; f=lang=="fa"
    pv=query.data.split(":")[2]; plan=_plan_str(user); allowed=_allowed(plan)
    if pv not in allowed:
        req="premium" if pv in PREMIUM_PLATFORMS else "pro"
        await query.edit_message_text(
            f"🔒 <b>"+("نیاز به ارتقا" if f else "Upgrade Required")+"</b>\n\n"+
            ("این پلتفرم نیاز به ارتقای پلن دارد." if f else f"This platform requires {req.upper()} plan."),
            parse_mode=ParseMode.HTML,reply_markup=locked_platform_upgrade(req,lang))
        return ConversationHandler.END
    try: platform=Platform(pv)
    except ValueError: return ConversationHandler.END
    plan_cfg=await _get_plan_cfg(user.plan)
    from bot.utils.keyboards import PLAN_ACCOUNT_LIMITS
    count=await _count_accounts(user.id)
    limit=(plan_cfg.max_accounts if plan_cfg else PLAN_ACCOUNT_LIMITS.get(plan,5))+(user.referral_bonus_accounts or 0)
    if count>=limit:
        await query.edit_message_text("⚠️ "+("سقف اکانت پر شده." if f else f"Account limit ({limit}) reached."),
                                      parse_mode=ParseMode.HTML,reply_markup=error_with_home(lang))
        try:
            from worker.growth import send_upsell_if_quota_full
            import asyncio; asyncio.ensure_future(send_upsell_if_quota_full(user.id,update.effective_user.id,lang))
        except Exception: pass
        return ConversationHandler.END
    await _set_last_platform(user.id,pv)
    context.user_data["adding_platform"]=platform; context.user_data["adding_raw"]=None
    example=PLATFORM_EXAMPLES.get(pv,""); plabel=PLATFORM_LABELS.get(pv,pv.title())
    await query.edit_message_text(
        f"➕ <b>{plabel}</b>\n\n"+("لینک یا نام کاربری را ارسال کنید:" if f else "Send the account link or username:")+
        (f"\n\n<code>{example}</code>" if example else "")+
        "\n\n📋 "+("نگه‌دار و پیست کن." if f else "Tip: long-press → Paste."),parse_mode=ParseMode.HTML)
    rm=await query.message.reply_text("⌨️",reply_markup=ReplyKeyboardRemove())
    try: await rm.delete()
    except Exception: pass
    return WAITING_LINK

async def cb_addacc_control(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    query=update.callback_query; await query.answer()
    user:Optional[User]=context.user_data.get("user")
    if not user: return ConversationHandler.END
    lang=user.language; f=lang=="fa"; action=query.data.split(":")[1]
    if action=="retry":
        platform=context.user_data.get("adding_platform")
        if not platform: return ConversationHandler.END
        plabel=PLATFORM_LABELS.get(platform.value,platform.value)
        example=PLATFORM_EXAMPLES.get(platform.value,"")
        await query.edit_message_text(
            f"➕ <b>{plabel}</b>\n\n"+("دوباره لینک را ارسال کنید:" if f else "Send the link again:")+
            (f"\n\n<code>{example}</code>" if example else ""),parse_mode=ParseMode.HTML)
        return WAITING_LINK
    elif action=="new":
        context.user_data.pop("adding_platform",None)
        await show_platform_selection(update,context,user)
        return ConversationHandler.END
    else:
        context.user_data.pop("adding_platform",None); context.user_data.pop("adding_raw",None)
        try: await query.message.delete()
        except Exception: pass
        return ConversationHandler.END

async def receive_link(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    user:Optional[User]=context.user_data.get("user")
    if not user: return ConversationHandler.END
    lang=user.language; f=lang=="fa"
    platform:Optional[Platform]=context.user_data.get("adding_platform")
    if not platform: return ConversationHandler.END
    raw=update.message.text.strip(); context.user_data["adding_raw"]=raw
    msg=await safe_send_message(update.effective_user.id,"🔍 "+("در حال شناسایی..." if f else "Detecting..."))
    from bot.services.platform_resolver import resolve_account
    try: resolved=await resolve_account(platform,raw)
    except Exception as e:
        logger.error(f"Resolve error: {e}")
        if msg:
            try: await msg.delete()
            except Exception: pass
        await safe_send_message(update.effective_user.id,"❌ "+("خطا. مجدد امتحان کن." if f else "Error. Try again."),reply_markup=error_account_keyboard(lang))
        return WAITING_LINK
    if msg:
        try: await msg.delete()
        except Exception: pass
    if resolved is None:
        await safe_send_message(update.effective_user.id,"❌ "+("اکانت یافت نشد." if f else "Account not found."),reply_markup=error_account_keyboard(lang))
        return WAITING_LINK
    if resolved.get("private"):
        await safe_send_message(update.effective_user.id,"🔒 "+("اکانت خصوصی است." if f else "Account is private."),reply_markup=error_account_keyboard(lang))
        return WAITING_LINK
    async with get_session() as s:
        from sqlalchemy import select
        existing=(await s.execute(select(Account).where(Account.user_id==user.id,Account.platform==platform,Account.identifier==resolved["identifier"]))).scalar_one_or_none()
        if existing:
            count=await _count_accounts(user.id)
            from bot.utils.keyboards import error_with_home
            await safe_send_message(update.effective_user.id,"⚠️ "+("این اکانت قبلاً اضافه شده." if f else "This account is already added."),
                                    reply_markup=error_with_home(lang,
                                        extra_cb="addacc:new", extra_label="➕ "+("پلتفرم دیگر" if f else "Try Another Platform")))
            await safe_send_message(update.effective_user.id,"🏠",
                                    reply_markup=main_menu(lang,_plan_str(user),_is_admin(context),count))
            context.user_data.pop("adding_platform",None)
            return ConversationHandler.END
        default_cat=(await s.execute(select(Category).where(Category.user_id==user.id,Category.is_default==True))).scalar_one_or_none()
        account=Account(user_id=user.id,category_id=default_cat.id if default_cat else None,
                        platform=platform,identifier=resolved["identifier"],
                        display_name=resolved.get("name",resolved["identifier"]),
                        feed_url=resolved.get("feed_url"),next_fetch_at=datetime.now(timezone.utc),
                        is_initial_fetch=True)
        s.add(account)
        await s.commit()
        await s.refresh(account)
        account_id = account.id
        account_display_name = account.display_name

    new_count=await _count_accounts(user.id)
    await safe_send_message(update.effective_user.id,
        "✅ <b>"+("اکانت اضافه شد!" if f else "Account added!")+"</b>\n"+f"<b>{account_display_name}</b>",
        parse_mode=ParseMode.HTML,reply_markup=main_menu(lang,_plan_str(user),_is_admin(context),new_count))
    try:
        from worker.tasks import fetch_account_task; fetch_account_task.delay(account_id)
    except Exception as e: logger.warning(f"Queue failed: {e}")
    context.user_data.pop("adding_platform",None); context.user_data.pop("adding_raw",None)
    return ConversationHandler.END

# ── CALLBACKS ─────────────────────────────────────────────────────────────────
async def cb_account_action(update:Update,context:ContextTypes.DEFAULT_TYPE)->None:
    query=update.callback_query; await query.answer()
    user:Optional[User]=context.user_data.get("user")
    if not user: return
    lang=user.language; f=lang=="fa"; parts=query.data.split(":"); action=parts[1]
    if action=="noop": return
    if action=="list":  await show_platform_list(update,context,user); return
    if action=="submenu":
        try: await query.message.delete()
        except Exception: pass
        await show_accounts_submenu(update,context,user); return
    if action=="platform":
        try: p=Platform(parts[2])
        except ValueError: return
        await show_platform_accounts(update,context,user,p,edit_query=query); return
    if action=="back_platform":
        pv=parts[2] if len(parts)>2 else context.user_data.get("current_platform","")
        try: p=Platform(pv)
        except ValueError: return
        await show_platform_accounts(update,context,user,p,edit_query=query); return
    account_id=int(parts[2]) if len(parts)>2 else None
    if account_id is None: return
    async with get_session() as s:
        from sqlalchemy import select
        acc=(await s.execute(select(Account).where(Account.id==account_id,Account.user_id==user.id))).scalar_one_or_none()
        if not acc: await query.answer("Not found.",show_alert=True); return
        if action=="toggle":
            acc.is_active=not acc.is_active; await s.flush()
            state=("فعال" if acc.is_active else "متوقف") if f else("Activated" if acc.is_active else "Paused")
            await query.answer(f"{'✅' if acc.is_active else '⏸'} {state}")
            platform=acc.platform
            fresh=(await s.execute(select(Account).where(Account.user_id==user.id,Account.platform==platform).order_by(Account.is_active.desc(),Account.display_name))).scalars().all()
            try: await query.edit_message_reply_markup(reply_markup=platform_detail_keyboard(fresh,platform.value,lang))
            except Exception: pass
        elif action=="delete":
            await query.edit_message_reply_markup(reply_markup=confirm_delete_account(account_id,lang))
        elif action=="confirm_delete":
            await s.delete(acc); await s.flush()
            await query.edit_message_text("🗑️ "+("اکانت حذف شد." if f else "Account deleted."))
        elif action=="cancel_delete":
            platform=acc.platform
            fresh=(await s.execute(select(Account).where(Account.user_id==user.id,Account.platform==platform).order_by(Account.is_active.desc(),Account.display_name))).scalars().all()
            await query.edit_message_reply_markup(reply_markup=platform_detail_keyboard(fresh,platform.value,lang))

async def cb_menu_main(update:Update,context:ContextTypes.DEFAULT_TYPE)->None:
    query=update.callback_query; await query.answer()
    user:Optional[User]=context.user_data.get("user")
    if not user: return
    count=await _count_accounts(user.id)
    await safe_send_message(update.effective_user.id,"🏠",
        reply_markup=main_menu(user.language,_plan_str(user),_is_admin(context),count))

async def cb_upsell(update:Update,context:ContextTypes.DEFAULT_TYPE)->None:
    query=update.callback_query; await query.answer()
    user:Optional[User]=context.user_data.get("user")
    lang=user.language if user else "en"; f=lang=="fa"; req=query.data.split(":")[1]
    await query.edit_message_text(
        "⭐️ "+(f"نیاز به پلن {req.upper()} دارد." if f else f"Requires the {req.upper()} plan."),
        parse_mode=ParseMode.HTML,reply_markup=locked_platform_upgrade(req,lang))

def register(app:Application)->None:
    conv=ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_add_account_start,pattern=r"^addacc:start$"),
            CallbackQueryHandler(cb_platform_selected,pattern=r"^addacc:platform:"),
        ],
        states={WAITING_LINK:[
            CallbackQueryHandler(cb_addacc_control,pattern=r"^addacc:(retry|new|cancel)$"),
            CallbackQueryHandler(cb_platform_selected,pattern=r"^addacc:platform:"),
            MessageHandler(filters.TEXT&~filters.COMMAND,receive_link),
        ]},
        fallbacks=[],per_user=True,per_chat=True,allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cb_account_action,pattern=r"^acc:"))
    app.add_handler(CallbackQueryHandler(cb_addacc_noop,   pattern=r"^addacc:noop$"))
    app.add_handler(CallbackQueryHandler(cb_upsell,        pattern=r"^upsell:"))
    app.add_handler(CallbackQueryHandler(cb_menu_main,     pattern=r"^menu:main$"))
    logger.info("Account handlers registered v4.2")
