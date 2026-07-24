"""
SocialtoFeed — Keyboards v4.2
Complete implementation of the final UI/UX spec.
"""
from __future__ import annotations
from typing import Optional
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from bot.utils.translator import t

PLATFORM_EMOJI = {
    "youtube":"🎬","twitter":"𝕏","instagram":"📸","rss":"📡",
    "tiktok":"🎵","linkedin":"💼","reddit":"🤖","telegram":"✈️",
    "bluesky":"🦋","mastodon":"🐘","threads":"🧵","facebook":"👥","discord":"🎮",
}
PLAN_EMOJI  = {"free":"🆓","pro":"⭐️","premium":"💎"}
PLAN_LABEL  = {"free":"Free","pro":"Pro","premium":"Premium"}
FREE_PLATFORMS    = {"youtube","twitter","rss","reddit","telegram"}
PRO_PLATFORMS     = {"instagram","linkedin","threads","bluesky","mastodon"}
PREMIUM_PLATFORMS = {"tiktok","facebook","discord"}
ALL_PLATFORMS     = list(FREE_PLATFORMS|PRO_PLATFORMS|PREMIUM_PLATFORMS)
AI_TRANSLATE_QUICK = [
    ("🇬🇧","en","English"),("🇪🇸","es","Español"),
    ("🇫🇷","fr","Français"),("🇩🇪","de","Deutsch"),
    ("🇸🇦","ar","العربية"),("🇮🇷","fa","فارسی"),
    ("🇨🇳","zh","中文"),("🇯🇵","ja","日本語"),
]

def _b(text,cb): return InlineKeyboardButton(text,callback_data=cb)
def _u(text,url): return InlineKeyboardButton(text,url=url)
def remove_keyboard(): return ReplyKeyboardRemove()

# ── MAIN MENU ─────────────────────────────────────────────────────────────────
PLAN_ACCOUNT_LIMITS = {"free": 5, "pro": 40, "premium": 100}  # v4.2.1 issue-10 fallback safety net

def main_menu(lang="en",plan="free",is_admin=False,account_count=0)->ReplyKeyboardMarkup:
    f=lang=="fa"
    acct_label=(f"📋 {'اکانت‌ها' if f else 'Accounts'} ({account_count})"
                if account_count>0 else f"➕ {'اکانت' if f else 'Account'}")
    # v4.2.1 issue-11: 2 buttons per row instead of 1
    rows=[
        [KeyboardButton("🔄 "+("بروزرسانی" if f else "Updates")), KeyboardButton(acct_label)],
        [KeyboardButton("👤 "+("پروفایل" if f else "Profile"))],
    ]
    if is_admin: rows.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(rows,resize_keyboard=True,is_persistent=False)

# ── ACCOUNTS SUBMENU ──────────────────────────────────────────────────────────
def accounts_submenu(lang="en",account_count=0,is_admin=False)->ReplyKeyboardMarkup:
    f=lang=="fa"
    rows=[[KeyboardButton("📋 "+("اکانت‌های من" if f else "My Accounts")), KeyboardButton("➕ "+("افزودن جدید" if f else "Add New"))],
          [KeyboardButton("↩️ "+("بازگشت" if f else "Back"))]]
    if is_admin: rows.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(rows,resize_keyboard=True)

# ── MY ACCOUNTS — Platform List ───────────────────────────────────────────────
def platform_list_keyboard(platforms_with_count,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    rows=[]
    for platform,count in platforms_with_count:
        e=PLATFORM_EMOJI.get(platform.value,"📡")
        label=(f"{e} {platform.value.title()} ({count})" if count>0
               else f"{e} {platform.value.title()}")
        rows.append([_b(label,f"acc:platform:{platform.value}")])
    rows.append([_b("➕ "+("افزودن اکانت جدید" if f else "Add New Account"),"addacc:start"),
                 _b("↩️ "+("بازگشت" if f else "Back"),"acc:submenu")])
    return InlineKeyboardMarkup(rows)

# ── PLATFORM DETAIL ───────────────────────────────────────────────────────────
def platform_detail_keyboard(accounts,platform_value,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    rows=[]
    for acc in accounts:
        status="🟢" if acc.is_active else "🔴"
        name=acc.display_name or acc.identifier
        rows.append([_b(f"{status} {name}",f"acc:noop:{acc.id}")])
        toggle=("⏸ "+("توقف" if f else "Pause") if acc.is_active
                else "▶️ "+("فعال‌سازی" if f else "Activate"))
        rows.append([_b(toggle,f"acc:toggle:{acc.id}"),
                     _b("🗑️ "+("حذف" if f else "Delete"),f"acc:delete:{acc.id}")])
    rows.append([_b("➕ "+("افزودن اکانت" if f else f"Add {platform_value.title()} Account"),
                    f"addacc:platform:{platform_value}"),
                 _b("↩️ "+("بازگشت" if f else "Back"),"acc:list")])
    return InlineKeyboardMarkup(rows)

def confirm_delete_account(account_id,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([[
        _b("✅ "+("بله، حذف شود" if f else "Yes, Delete"),f"acc:confirm_delete:{account_id}"),
        _b("❌ "+("لغو" if f else "Cancel"),f"acc:cancel_delete:{account_id}"),
    ]])

# ── PLATFORM SELECTION (ADD NEW) ──────────────────────────────────────────────
def platform_keyboard(user_plan="free",user_platforms=None,last_platform=None,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    user_platforms=user_platforms or set()
    plan=user_plan.lower()
    def accessible(pv):
        if pv in FREE_PLATFORMS: return True
        if pv in PRO_PLATFORMS:  return plan in("pro","premium")
        return plan=="premium"
    added    =[p for p in ALL_PLATFORMS if p in user_platforms and accessible(p)]
    available=[p for p in ALL_PLATFORMS if p not in user_platforms and accessible(p)]
    pro_locked  =[p for p in PRO_PLATFORMS if not accessible(p)]
    prem_locked =[p for p in PREMIUM_PLATFORMS if not accessible(p)]
    rows=[]
    def pbtn(pv,badge=""):
        e=PLATFORM_EMOJI.get(pv,"📡")
        star=" ⭐" if pv==last_platform else ""
        return _b(f"{badge}{e} {pv.title()}{star}",f"addacc:platform:{pv}")
    if added:
        rows.append([_b("─── "+("افزوده شده" if f else "Added")+" ✅ ───","addacc:noop")])
        for i in range(0,len(added),2): rows.append([pbtn(p,"✅ ") for p in added[i:i+2]])
    if available:
        rows.append([_b("─── "+("موجود" if f else "Available")+" ───","addacc:noop")])
        for i in range(0,len(available),2): rows.append([pbtn(p) for p in available[i:i+2]])
    if pro_locked:
        rows.append([_b("🔒 Pro ⭐️ — "+("اینستاگرام و بیشتر" if f else "Instagram & more"),"upsell:pro")])
    if prem_locked:
        rows.append([_b("🔒 Premium 💎 — "+("تیک‌تاک و بیشتر" if f else "TikTok & more"),"upsell:premium")])
    rows.append([_b("↩️ "+("بازگشت" if f else "Back"),"acc:submenu")])
    return InlineKeyboardMarkup(rows)

def locked_platform_upgrade(required_plan,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("🔓 "+("مشاهده پلن‌ها" if f else "View Plans"),"pay:back:plans")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"addacc:start")],
    ])

def error_account_keyboard(lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("🔄 "+("تلاش مجدد" if f else "Try Again"),"addacc:retry")],
        [_b("➕ "+("پلتفرم دیگر" if f else "Other Platform"),"addacc:new")],
        [_b("❌ "+("لغو" if f else "Cancel"),"addacc:cancel"),
         _b("🏠 "+("خانه" if f else "Home"),"menu:main")],
    ])

# ── PROFILE ───────────────────────────────────────────────────────────────────
def profile_menu(lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("💳 "+("اشتراک" if f else "Subscription"),"profile:subscription")],
        [_b("📤 "+("دعوت از دوستان" if f else "Referral"),"profile:referral")],
        [_b("⚙️ "+("تنظیمات" if f else "Settings"),"profile:settings")],
        [_b("❓ "+("راهنما" if f else "Help"),"profile:help")],
        [_b("🔖 "+("بوک‌مارک‌ها" if f else "My Bookmarks"),"profile:bookmarks")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"menu:main")],
    ])

# ── SUBSCRIPTION ──────────────────────────────────────────────────────────────
def subscription_menu(lang,plan,expires_days,price_monthly)->InlineKeyboardMarkup:
    f=lang=="fa"
    rows=[]
    if plan=="free":
        rows+=[[_b("⭐️ "+("ارتقا به Pro" if f else "Upgrade to Pro"),"pay:plan:pro")],
               [_b("💎 "+("ارتقا به Premium" if f else "Upgrade to Premium"),"pay:plan:premium")]]
    elif plan=="pro":
        rows+=[[_b("💎 "+("ارتقا به Premium" if f else "Upgrade to Premium"),"pay:plan:premium")],
               [_b("🔄 "+("تمدید Pro" if f else "Renew Pro"),"pay:plan:pro")]]
    else:
        rows.append([_b("🔄 "+("تمدید Premium" if f else "Renew Premium"),"pay:plan:premium")])
    rows+=[[_b("📊 "+("مقایسه پلن‌ها" if f else "Compare Plans"),"sub:compare")],
           [_b("📋 "+("تاریخچه پرداخت" if f else "Payment History"),"sub:history")],
           [_b("↩️ "+("بازگشت" if f else "Back"),"profile:menu")]]
    return InlineKeyboardMarkup(rows)

def compare_plans_keyboard(lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("⭐️ "+("بگیر Pro" if f else "Get Pro"),"pay:plan:pro"),
         _b("💎 "+("بگیر Premium" if f else "Get Premium"),"pay:plan:premium")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:subscription")],
    ])

def period_keyboard(plan,lang,prices)->InlineKeyboardMarkup:
    f=lang=="fa"
    m=prices.get("monthly",0.0); bi=prices.get("biannual",0.0); yr=prices.get("yearly",0.0)
    dbi=round((m*6-bi)/(m*6)*100) if m else 0
    dyr=round((m*12-yr)/(m*12)*100) if m else 0
    return InlineKeyboardMarkup([
        [_b(f"📅 {'ماهانه' if f else 'Monthly'} — ${m:.0f} USDT",f"pay:period:{plan}:monthly")],
        [_b(f"🔥 {'۶ ماهه' if f else '6 Months'} — ${bi:.0f} USDT ({dbi}% off) ⭐️",f"pay:period:{plan}:biannual")],
        [_b(f"⚡️ {'سالانه' if f else 'Yearly'} — ${yr:.0f} USDT ({dyr}% off)",f"pay:period:{plan}:yearly")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:subscription")],
    ])

def payment_method_keyboard(plan,period,lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("💎 "+("کریپتو USDT" if f else "Crypto (USDT)"),f"pay:method:{plan}:{period}:crypto")],
        [_b("💳 "+("کارت اعتباری 🔜" if f else "Credit Card 🔜"),"pay:coming_soon:card")],
        [_b("📱 Apple Pay 🔜","pay:coming_soon:apple")],
        [_b("🤖 Google Pay 🔜","pay:coming_soon:google")],
        [_b("❌ "+("لغو" if f else "Cancel"),"profile:subscription")],
    ])

# ── REFERRAL ──────────────────────────────────────────────────────────────────
def referral_menu(lang,points,next_milestone)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("📤 "+("اشتراک‌گذاری لینک" if f else "Share Referral Link"),"referral:share")],
        [_b("🎁 "+("مشاهده جوایز" if f else "View Rewards"),"referral:rewards")],
        [_b("📋 "+("تاریخچه رفرال" if f else "Referral History"),"referral:history")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:menu")],
    ])

def referral_share_keyboard(lang,referral_link,points)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 "+("اشتراک‌گذاری" if f else "Share"),switch_inline_query=referral_link)],
        [_b("📋 "+("کپی لینک" if f else "Copy Link"),f"referral:copy")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"referral:menu")],
    ])

def referral_rewards_keyboard(lang,points)->InlineKeyboardMarkup:
    f=lang=="fa"
    REWARDS=[(5,"pro_week","⭐️ 1 week Pro"),(10,"pro_month","⭐️ 1 month Pro"),
             (20,"premium_month","💎 1 month Premium"),(50,"premium_3month","💎 3 months Premium")]
    rows=[]
    for cost,key,label in REWARDS:
        if points>=cost:
            rows.append([_b(f"{label} — {cost} pts",f"referral:redeem:{cost}:{key}")])
        else:
            rows.append([_b(f"🔒 {label} — {cost} pts (need {cost-points} more)","referral:need_more")])
    rows.append([_b("↩️ "+("بازگشت" if f else "Back"),"referral:menu")])
    return InlineKeyboardMarkup(rows)

# ── SETTINGS ──────────────────────────────────────────────────────────────────
def fetch_interval_keyboard(lang, current_minutes=30)->InlineKeyboardMarkup:
    """v4.2.1 issue-13: Premium-only fetch interval selector 10/30/60 min."""
    f=lang=="fa"
    def opt(m):
        check="✅ " if current_minutes==m else ""
        return _b(f"{check}{m} "+("دقیقه" if f else "min"),f"settings:fetchint:{m}")
    return InlineKeyboardMarkup([
        [opt(10), opt(30), opt(60)],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:settings")],
    ])

def home_button(lang="en")->InlineKeyboardMarkup:
    """v4.2.1 issue-1: attached to bare error/warning messages so users are never stuck."""
    f=lang=="fa"
    return InlineKeyboardMarkup([[_b("🏠 "+("منوی اصلی" if f else "Home"),"menu:main")]])

def error_with_home(lang="en", extra_cb=None, extra_label=None)->InlineKeyboardMarkup:
    """v4.2.1 issue-1/8/9: error/duplicate messages get Home + optional Cancel/Retry action."""
    f=lang=="fa"
    rows=[]
    if extra_cb and extra_label:
        rows.append([_b(extra_label, extra_cb)])
    rows.append([_b("🏠 "+("منوی اصلی" if f else "Home"),"menu:main")])
    return InlineKeyboardMarkup(rows)



def settings_menu(lang,plan,spam_filter=False,email_digest=False,
                  ai_active_count=0,footer_enabled=True,channel_set=False,
                  fetch_interval=30)->InlineKeyboardMarkup:
    f=lang=="fa"
    premium=plan=="premium"
    pro_plus=plan in("pro","premium")
    def locked(label): return _b(f"🔒 {label}","settings:locked:premium")
    rows=[[_b("🌐 "+("زبان" if f else "Language"),"settings:language")]]
    rows.append([_b(("✅" if spam_filter else "⬜️")+f" 🚫 "+("فیلتر اسپم" if f else "Spam Filter"),"settings:toggle:spam")]
                if premium else [locked("🚫 "+("فیلتر اسپم" if f else "Spam Filter"))])
    rows.append([_b(("✅" if email_digest else "⬜️")+f" 📧 "+("دایجست ایمیل" if f else "Email Digest"),"settings:toggle:digest")]
                if premium else [locked("📧 "+("دایجست ایمیل" if f else "Email Digest"))])
    rows.append([_b(f"🤖 "+("ویژگی‌های AI" if f else f"AI Features ({ai_active_count}/4 active)"),"settings:ai")]
                if premium else [locked("🤖 "+("ویژگی‌های AI" if f else "AI Features"))])
    rows.append([_b("📤 "+("خروجی داده" if f else "Export Data"),"settings:export")]
                if pro_plus else [locked("📤 "+("خروجی داده" if f else "Export Data"))])
    rows.append([_b(("✅" if footer_enabled else "⬜️")+" 📎 "+("فوتر" if f else "Footer Toggle"),"settings:toggle:footer")]
                if premium else [locked("📎 "+("فوتر" if f else "Footer Toggle"))])
    rows.append([_b(("✅" if channel_set else "📺")+" "+("فوروارد به کانال" if f else "Channel Forward"),"settings:channel")]
                if premium else [locked("📺 "+("فوروارد به کانال" if f else "Channel Forward"))])
    # v4.2.1 issue-13: fetch interval, Premium only
    rows.append([_b(f"⏱ "+("زمان دریافت" if f else "Fetch Interval")+f" ({fetch_interval} "+("دقیقه" if f else "min")+")","settings:fetchinterval")]
                if premium else [locked("⏱ "+("زمان دریافت" if f else "Fetch Interval"))])
    rows.append([_b("↩️ "+("بازگشت" if f else "Back"),"profile:menu")])
    return InlineKeyboardMarkup(rows)

def settings_locked_upgrade(lang)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("🔓 "+("مشاهده پلن‌ها" if f else "View Plans"),"pay:back:plans")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:settings")],
    ])

# ── AI FEATURES ───────────────────────────────────────────────────────────────
def ai_features_menu(lang,summarize,translate,categorize,spam_tag,translate_lang="fa")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b(("✅" if summarize else "⬜️")+" "+("خلاصه‌سازی" if f else "AI Summarize"),"ai:toggle:summarize")],
        [
            _b(("✅" if translate else "⬜️")+" "+("ترجمه" if f else "AI Translate")+f" → {translate_lang}","ai:toggle:translate"),
            _b("⚙️","ai:translate:settings")
        ],
        [_b(("✅" if categorize else "⬜️")+" "+("دسته‌بندی" if f else "AI Categorize"),"ai:toggle:categorize")],
        [_b(("✅" if spam_tag else "⬜️")+" "+("تشخیص اسپم" if f else "AI Spam Tagging"),"ai:toggle:spam_tag")],
        [
            _b("⚡️ "+("فعال‌سازی همه" if f else "Enable All"),"ai:enable_all"),
            _b("🛑 "+("غیرفعال‌سازی همه" if f else "Disable All"),"ai:disable_all")
        ],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:settings")],
    ])

def ai_translate_menu(lang,current_lang_code="fa")->InlineKeyboardMarkup:
    f=lang=="fa"
    rows=[]
    for i in range(0,len(AI_TRANSLATE_QUICK),2):
        pair=AI_TRANSLATE_QUICK[i:i+2]
        rows.append([_b(f"{flag} {name}",f"ai:setlang:{code}") for flag,code,name in pair])
    rows.append([_b("✏️ "+("تایپ نام زبان..." if f else "Type language name..."),"ai:setlang:custom")])
    rows.append([_b("↩️ "+("بازگشت" if f else "Back"),"settings:ai")])
    return InlineKeyboardMarkup(rows)

# ── HELP ──────────────────────────────────────────────────────────────────────
def help_menu(lang,plan)->InlineKeyboardMarkup:
    f=lang=="fa"
    is_premium=plan=="premium"
    rows=[
        [_b("📖 "+("سوالات متداول" if f else "FAQ"),"help:faq")],
        [_b("🎫 "+("تیکت‌های من" if f else "My Tickets"),"help:tickets")],
        [_b("➕ "+("تیکت جدید" if f else "New Ticket"),"help:new_ticket")],
    ]
    rows.append([_b("🤖 "+("چت AI" if f else "AI Chat"),"help:ai_chat")]
                if is_premium else
                [_b("🔒 🤖 "+("چت AI — فقط Premium" if f else "AI Chat — Premium only"),"help:ai_chat_locked")])
    rows+=[
        [_b("📧 "+("تماس با پشتیبانی" if f else "Contact Support"),"help:contact")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:menu")],
    ]
    return InlineKeyboardMarkup(rows)

    return InlineKeyboardMarkup(rows)

def contact_support_keyboard(lang)->InlineKeyboardMarkup:
    """v4.2.1 fix: Telegram rejects mailto: as invalid URL for inline buttons
    (only http(s):// and tg:// schemes are allowed). Email shown as plain
    copyable text in the message body instead; only Ticket is a real button."""
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("🎫 "+("باز کردن تیکت" if f else "Open a Ticket"),"help:new_ticket")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:help")],
    ])

def ticket_subjects(lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    subjects=[("technical","🔧 "+("مشکل فنی" if f else "Technical Issue")),
              ("payment","💳 "+("پرداخت" if f else "Payment")),
              ("general","❓ "+("سوال عمومی" if f else "General Question")),
              ("report","🚩 "+("گزارش تخلف" if f else "Report Abuse"))]
    rows=[[_b(label,f"ticket:subject:{key}")] for key,label in subjects]
    rows.append([_b("↩️ "+("بازگشت" if f else "Back"),"profile:help")])
    return InlineKeyboardMarkup(rows)

def ai_chat_locked_keyboard(lang)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("🔓 "+("مشاهده پلن‌ها" if f else "View Plans"),"pay:back:plans")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"profile:help")],
    ])

# ── POST BUTTONS ──────────────────────────────────────────────────────────────
def post_buttons(platform,url,url_key,lang,can_download_link=False,can_download_file=False,
                 can_audio_link=False,can_audio_file=False,can_ai=False,has_video=False,plan="free")->InlineKeyboardMarkup:
    f=lang=="fa"; is_premium=plan=="premium"; show_ai=can_ai and is_premium
    rows=[]
    r1=[InlineKeyboardButton("🔗 "+("مشاهده" if f else "View"),url=url)]
    if show_ai: r1.append(_b("🤖 "+("خلاصه" if f else "Summary"),f"ai:summary:{url_key}"))
    rows.append(r1)
    if has_video:
        r2=[]
        if can_download_link: r2.append(_b("⬇️ "+("لینک" if f else "Link"),f"vq:{url_key}"))
        if can_audio_link or can_audio_file: r2.append(_b("🎵 "+("صدا" if f else "Audio"),f"vaudio:{url_key}"))
        if can_download_file: r2.append(_b("📥 "+("فایل" if f else "File"),f"vdl:{url_key}"))
        if r2: rows.append(r2)
    r3=[_b("🔖 "+("ذخیره" if f else "Save"),f"bm:save:{platform}:{url_key}")]
    if show_ai: r3.append(_b("🌐 "+("ترجمه" if f else "Translate"),f"ai:translate:{url_key}"))
    rows.append(r3)
    return InlineKeyboardMarkup(rows)

# ── MISC ──────────────────────────────────────────────────────────────────────
def language_keyboard()->InlineKeyboardMarkup:
    from bot.utils.translator import SUPPORTED_LANGUAGES
    codes=list(SUPPORTED_LANGUAGES.keys())
    rows=[[_b(SUPPORTED_LANGUAGES[c],f"setlang:{c}") for c in codes[i:i+2]]
          for i in range(0,len(codes),2)]
    return InlineKeyboardMarkup(rows)

def back_button(lang="en",callback="menu:main")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([[_b("↩️ "+("بازگشت" if f else "Back"),callback)]])

def back_keyboard(lang="en",callback="menu:main")->InlineKeyboardMarkup:
    return back_button(lang,callback)

def confirm_keyboard(lang,action_cb)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([[_b("✅ "+("بله" if f else "Yes"),action_cb),
                                  _b("❌ "+("خیر" if f else "No"),"action:cancel")]])

def status_keyboard(lang)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([[_b("💳 "+("تمدید" if f else "Renew"),"profile:subscription"),
                                  _b("📱 "+("اکانت‌ها" if f else "Accounts"),"acc:list")]])

# ── ADMIN ─────────────────────────────────────────────────────────────────────
def admin_main_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("📊 Dashboard","adm:dashboard")],
        [_b("👥 Users","adm:users"), _b("💰 Revenue","adm:revenue")],
        [_b("📢 Broadcast","adm:broadcast"), _b("🖥 System","adm:system")],
        [_b("🚨 Alerts","adm:alerts"), _b("🔍 Debug","adm:debug")],
    ])

def admin_user_actions(user_id,is_banned)->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("✅ Unban" if is_banned else "🚫 Ban",
            f"adm:unban:{user_id}" if is_banned else f"adm:ban:{user_id}")],
        [_b("🎁 Grant Plan",f"adm:grant:{user_id}")],
        [_b("📩 Send Message",f"adm:msg:{user_id}")],
        [_b("🗑️ Delete User",f"adm:deluser:{user_id}")],
        [_b("↩️ Back","adm:users")],
    ])

def admin_grant_plan(user_id)->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("⭐ Pro 30d",f"adm:grantplan:{user_id}:pro:30"),
         _b("⭐ Pro 90d",f"adm:grantplan:{user_id}:pro:90")],
        [_b("💎 Premium 30d",f"adm:grantplan:{user_id}:premium:30"),
         _b("💎 Premium 90d",f"adm:grantplan:{user_id}:premium:90")],
        [_b("🆓 Free",f"adm:grantplan:{user_id}:free:0")],
        [_b("✏️ Custom Plan",f"adm:grantcustom:{user_id}")],
        [_b("❌ Cancel",f"adm:userdetail:{user_id}")],
    ])

def admin_broadcast_targets()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("👥 All Users","adm:bc:all"),_b("⭐ Pro","adm:bc:pro")],
        [_b("💎 Premium","adm:bc:premium"),_b("❌ Cancel","adm:bc:cancel")],
    ])

def admin_confirm(action,label)->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(f"✅ Confirm {label}",f"adm:confirm:{action}"),
                                  _b("❌ Cancel","adm:cancel")]])

# ── COMPAT ALIASES ────────────────────────────────────────────────────────────
def add_account_button(lang="en")->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("➕ Add Account","addacc:start")]])

def subscription_keyboard(lang="en")->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [_b("⭐️ Pro","pay:plan:pro")],
        [_b("💎 Premium","pay:plan:premium")],
        [_b("🔍 "+("مقایسه پلن‌ها" if f else "Compare Plans"),"sub:compare")],
        [_b("↩️ "+("بازگشت" if f else "Back"),"menu:main")],
    ])

def plan_selection(lang="en")->InlineKeyboardMarkup:
    return subscription_keyboard(lang)

def period_selection(plan,lang="en")->InlineKeyboardMarkup:
    return period_keyboard(plan,lang,{})

def share_bot_keyboard(lang,referral_link)->InlineKeyboardMarkup:
    f=lang=="fa"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 "+("معرفی به دوستان" if f else "Share with friends"),
                              switch_inline_query=referral_link)],
        [_b("❌ "+("دیگه نشون نده" if f else "Don't show again"),"share:dismiss")],
    ])

def settings_keyboard(lang,**kw)->InlineKeyboardMarkup:
    return settings_menu(lang,plan=kw.get("plan","free"),
                         spam_filter=kw.get("spam_filter",False),
                         email_digest=kw.get("email_digest",False),
                         footer_enabled=kw.get("footer_enabled",True),
                         channel_set=kw.get("channel_set",False))

def admin_dashboard_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("⬅️ Back", "adm:menu")]
    ])

def admin_users_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("🔍 Search User", "adm:usersearch")],
        [_b("📊 User Stats", "adm:users:stats"), _b("📋 Recent Users", "adm:users:recent")],
        [_b("🚫 Banned Users", "adm:users:banned"), _b("📋 Pending Verifications", "adm:users:pending")],
        [_b("⬅️ Back", "adm:menu")]
    ])

def admin_revenue_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("📊 Total Revenue", "adm:rev:total"), _b("📈 This Month", "adm:rev:month")],
        [_b("📅 Today", "adm:rev:today"), _b("💳 Recent Transactions", "adm:txs")],
        [_b("⭐ Pro Subscriptions", "adm:rev:pro"), _b("💎 Premium Subscriptions", "adm:rev:premium")],
        [_b("🔄 Renewals", "adm:rev:renewals")],
        [_b("📊 Revenue Chart", "adm:rev:chart:revenue"), _b("📊 Plan Breakdown", "adm:rev:chart:plan")],
        [_b("⬅️ Back", "adm:menu")]
    ])

def admin_system_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("📋 System Logs", "adm:sys:logs")],
        [_b("⬅️ Back", "adm:menu")]
    ])

def admin_alerts_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("🗑️ Clear All Logs", "adm:alerts:clear")],
        [_b("📤 Export Error Logs", "adm:alerts:export")],
        [_b("⬅️ Back", "adm:menu")]
    ])

def admin_debug_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("🧪 Test Features", "adm:debug:test"), _b("📊 Performance", "adm:debug:perf")],
        [_b("🔍 SQL Query Runner", "adm:debug:sql"), _b("🔄 Force Sync", "adm:debug:sync")],
        [_b("📋 Export Debug Logs", "adm:debug:export"), _b("📧 Send Debug Report", "adm:debug:report")],
        [_b("⬅️ Back", "adm:menu")]
    ])
