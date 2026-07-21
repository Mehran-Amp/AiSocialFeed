"""
SocialtoFeed — Video Handler
Handles video streaming preview and quality-based link extraction.

Flow:
1. Post arrives → if has video → send with preview enabled (streams in Telegram)
2. User taps "⬇️ دانلود" → show quality buttons (480p / 720p / 1080p)
3. User picks quality → send direct link
4. Premium users also see "📥 دانلود فایل" button for actual file download
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from bot.models import PlanType, User
from bot.services.video_extractor import (
    VideoInfo, VideoQuality,
    extract_video_info, format_duration, format_filesize,
)
from bot.utils.fixes import safe_send_fixed
from bot.utils.telegram_utils import get_bot
from bot.utils.translator import t
from bot.utils.keyboards import home_button

logger = logging.getLogger(__name__)

# PERF-2 fix: bounded TTL cache — max 500 entries, 30-minute TTL enforced.
# The original plain dict had no expiry and grew without bound in production.
try:
    from cachetools import TTLCache
    _video_cache: TTLCache = TTLCache(maxsize=500, ttl=1800)
except ImportError:
    # cachetools not installed — fall back to plain dict with a warning
    import warnings
    warnings.warn(
        "cachetools not installed; video cache has no TTL. Run: pip install cachetools",
        RuntimeWarning,
        stacklevel=1,
    )
    _video_cache: dict = {}


# ─────────────────────────────────────────────
#  Quality Selection Keyboard
# ─────────────────────────────────────────────

def _quality_keyboard(
    video_url: str,
    qualities: list[VideoQuality],
    user: User,
    lang: str,
) -> InlineKeyboardMarkup:
    """
    Shows available quality buttons.
    Premium users also see a "Download File" button.
    """
    buttons = []

    for q in qualities:
        size_str = f" ({format_filesize(q.filesize_mb)})" if q.filesize_mb else ""
        label = f"🎬 {q.label}{size_str}"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"vlink:{q.height}:{_encode_url(video_url)}",
        )])

    # Premium: actual file download button
    if user.plan == PlanType.PREMIUM:
        buttons.append([InlineKeyboardButton(
            "📥 دانلود فایل (پریمیوم)" if lang == "fa" else "📥 Download File (Premium)",
            callback_data=f"vdl:{_encode_url(video_url)}",
        )])

    buttons.append([InlineKeyboardButton(
        t("menu.back", lang), callback_data="video:cancel"
    )])

    return InlineKeyboardMarkup(buttons)


def _encode_url(url: str) -> str:
    """Encode URL for callback_data (max 64 chars total)."""
    import hashlib
    # Store full URL in cache, use hash as key in callback
    key = hashlib.md5(url.encode()).hexdigest()[:16]
    _video_cache[f"url:{key}"] = url
    return key


def _decode_url(key: str) -> Optional[str]:
    return _video_cache.get(f"url:{key}")


# ─────────────────────────────────────────────
#  Show Quality Selection
# ─────────────────────────────────────────────

async def show_quality_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Called when user taps ⬇️ دانلود button under a post."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return

    lang = user.language

    # Extract URL from callback data: "vq:URL_HASH"
    url_key = query.data.split(":", 1)[1]
    original_url = _decode_url(url_key)

    if not original_url:
        await query.edit_message_text("⚠️ لینک منقضی شده. پست رو دوباره باز کن.", reply_markup=home_button(lang))
        return

    # Show loading
    await query.edit_message_text(
        "⏳ در حال دریافت کیفیت‌های موجود..." if lang == "fa"
        else "⏳ Fetching available qualities...",
    )

    # Check cache
    cached = _video_cache.get(original_url)
    if not cached:
        cached = await extract_video_info(original_url)
        if not cached.error:
            _video_cache[original_url] = cached

    if cached.error or not cached.qualities:
        await query.edit_message_text(
            "⚠️ کیفیتی برای دانلود پیدا نشد.\n"
            f"لینک مستقیم: {original_url}" if lang == "fa"
            else f"⚠️ No downloadable quality found.\nDirect link: {original_url}"
        )
        return

    # Build quality selection message
    duration_str = format_duration(cached.duration_seconds)
    text = (
        f"🎬 <b>{cached.title[:60]}</b>\n"
        f"{'⏱ ' + duration_str if duration_str else ''}\n\n"
        f"{'کیفیت دانلود رو انتخاب کن:' if lang == 'fa' else 'Select download quality:'}"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_quality_keyboard(original_url, cached.qualities, user, lang),
    )


# ─────────────────────────────────────────────
#  Send Direct Link for Selected Quality
# ─────────────────────────────────────────────

async def send_quality_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """User selected a quality → send direct stream URL."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    lang = user.language if user else "en"

    # Parse: "vlink:HEIGHT:URL_KEY"
    parts = query.data.split(":", 2)
    height = int(parts[1])
    url_key = parts[2]
    original_url = _decode_url(url_key)

    if not original_url:
        await query.edit_message_text("⚠️ لینک منقضی شده.", reply_markup=home_button(lang))
        return

    # Get cached info
    cached = _video_cache.get(original_url)
    if not cached:
        await query.edit_message_text("⚠️ اطلاعات ویدیو پیدا نشد.", reply_markup=home_button(lang))
        return

    # Find requested quality
    quality = next((q for q in cached.qualities if q.height == height), None)
    if not quality:
        await query.edit_message_text("⚠️ این کیفیت دیگه در دسترس نیست.", reply_markup=home_button(lang))
        return

    size_str = format_filesize(quality.filesize_mb) if quality.filesize_mb else ""

    text = (
        f"🎬 <b>{cached.title[:60]}</b>\n"
        f"📊 کیفیت: <b>{quality.label}</b>"
        f"{' · ' + size_str if size_str else ''}\n\n"
        f"🔗 <a href='{quality.url}'>لینک مستقیم</a>\n\n"
        f"⏰ این لینک حدود ۶ ساعت معتبره.\n"
        f"💡 لینک رو توی مرورگر یا دانلود منیجر باز کن."
    ) if lang == "fa" else (
        f"🎬 <b>{cached.title[:60]}</b>\n"
        f"📊 Quality: <b>{quality.label}</b>"
        f"{' · ' + size_str if size_str else ''}\n\n"
        f"🔗 <a href='{quality.url}'>Direct Link</a>\n\n"
        f"⏰ This link is valid for ~6 hours.\n"
        f"💡 Open in browser or download manager."
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────
#  Premium: Actual File Download
# ─────────────────────────────────────────────

async def start_file_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Premium only: show quality buttons for actual file download."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user or user.plan != PlanType.PREMIUM:
        await query.answer("این قابلیت فقط برای پریمیوم", show_alert=True)
        return

    lang = user.language
    url_key = query.data.split(":", 1)[1]
    original_url = _decode_url(url_key)

    if not original_url:
        await query.edit_message_text("⚠️ لینک منقضی شده.", reply_markup=home_button(lang))
        return

    cached = _video_cache.get(original_url)
    if not cached or not cached.qualities:
        await query.edit_message_text("⚠️ اطلاعات ویدیو پیدا نشد.", reply_markup=home_button(lang))
        return

    # Show quality buttons for actual download
    buttons = []
    for q in cached.qualities:
        size_str = f" ({format_filesize(q.filesize_mb)})" if q.filesize_mb else ""
        icon = "⚠️" if (q.filesize_mb or 0) > 50 else "✅"
        note = " (لینک)" if (q.filesize_mb or 0) > 50 else ""
        buttons.append([InlineKeyboardButton(
            f"{icon} {q.label}{size_str}{note}",
            callback_data=f"vdlq:{q.height}:{url_key}",
        )])

    buttons.append([InlineKeyboardButton(
        t("menu.back", lang), callback_data=f"vq:{url_key}"
    )])

    text = (
        "📥 <b>دانلود فایل ویدیو</b>\n\n"
        "کیفیت مورد نظر رو انتخاب کن:\n"
        "✅ = ارسال فایل مستقیم\n"
        "⚠️ = حجم بیشتر از ۵۰MB — لینک مستقیم ارسال میشه"
    ) if lang == "fa" else (
        "📥 <b>Download Video File</b>\n\n"
        "Select quality:\n"
        "✅ = Send file directly\n"
        "⚠️ = Over 50MB — direct link will be sent"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def download_file_quality(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Premium: Download actual file for selected quality."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user or user.plan != PlanType.PREMIUM:
        return

    lang = user.language
    parts = query.data.split(":", 2)
    height = int(parts[1])
    url_key = parts[2]
    original_url = _decode_url(url_key)

    if not original_url:
        await query.edit_message_text("⚠️ لینک منقضی شده.", reply_markup=home_button(lang))
        return

    cached = _video_cache.get(original_url)
    quality = next((q for q in (cached.qualities if cached else []) if q.height == height), None)

    if not quality:
        await query.edit_message_text("⚠️ کیفیت پیدا نشد.", reply_markup=home_button(lang))
        return

    # If over 50MB → send direct link instead
    if quality.filesize_mb and quality.filesize_mb > 50:
        await query.edit_message_text(
            f"📦 حجم {format_filesize(quality.filesize_mb)} از حد تلگرام بیشتره.\n\n"
            f"🔗 <a href='{quality.url}'>لینک مستقیم {quality.label}</a>\n\n"
            f"⏰ معتبر تا ~۶ ساعت" if lang == "fa" else
            f"📦 {format_filesize(quality.filesize_mb)} exceeds Telegram limit.\n\n"
            f"🔗 <a href='{quality.url}'>Direct Link {quality.label}</a>\n\n"
            f"⏰ Valid for ~6 hours",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    # Queue actual download via Celery
    await query.edit_message_text(
        f"⏳ در حال دانلود {quality.label}...\n"
        f"وقتی آماده شد برات میفرستم." if lang == "fa" else
        f"⏳ Downloading {quality.label}...\n"
        f"I'll send it when ready."
    )

    from worker.tasks import download_video_task
    download_video_task.apply_async(
        args=[user.telegram_id, original_url, f"{height}p"],
        queue="default",
    )


# ─────────────────────────────────────────────
#  Post Formatting — with video preview
# ─────────────────────────────────────────────

def build_post_buttons_with_video(
    platform: str,
    original_url: str,
    has_video: bool,
    user: User,
    lang: str,
) -> InlineKeyboardMarkup:
    """
    Build buttons for a post.
    Row 1: View original
    Row 2: Download link + Audio (if video)
    Row 3: Download file (premium) + Bookmark
    """
    url_key = _encode_url(original_url)
    buttons = []

    # Row 1: View original (always)
    buttons.append([InlineKeyboardButton(
        t("post.view_original", lang),
        url=original_url,
    )])

    if has_video:
        row2 = []
        # Download link quality selector (all plans)
        row2.append(InlineKeyboardButton(
            "⬇️ لینک دانلود" if lang == "fa" else "⬇️ Download Link",
            callback_data=f"vq:{url_key}",
        ))
        # Audio only (all plans)
        row2.append(InlineKeyboardButton(
            "🎵 فقط صدا" if lang == "fa" else "🎵 Audio Only",
            callback_data=f"vaudio:{url_key}",
        ))
        buttons.append(row2)

        # Premium: actual file download
        if user.plan == PlanType.PREMIUM:
            buttons.append([InlineKeyboardButton(
                "📥 دانلود فایل" if lang == "fa" else "📥 Download File",
                callback_data=f"vdl:{url_key}",
            )])

    # Bookmark button (all plans, all posts)
    from bot.handlers.bookmarks import make_bookmark_button
    buttons.append([make_bookmark_button(platform, url_key, lang)])

    return InlineKeyboardMarkup(buttons)


def should_preview_url(platform: str, url: str) -> bool:
    """
    Returns True if Telegram should show web preview for this URL.
    YouTube, Twitter with video = True (streams inside Telegram).
    RSS, LinkedIn = False (clutters the chat).
    """
    preview_platforms = {
        "youtube", "twitter", "instagram",
        "tiktok", "reddit", "telegram",
    }
    return platform.lower() in preview_platforms


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

async def send_audio_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Extract and send audio-only link for a video post."""
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    lang = user.language if user else "en"

    url_key = query.data.split(":", 1)[1]
    original_url = _decode_url(url_key)

    if not original_url:
        await query.edit_message_text("⚠️ لینک منقضی شده.", reply_markup=home_button(lang))
        return

    await query.edit_message_text(
        "⏳ در حال استخراج لینک صدا..." if lang == "fa"
        else "⏳ Extracting audio link..."
    )

    from bot.services.ai_service import AIService
    audio_info = await AIService.extract_audio_link(original_url)

    if not audio_info or not audio_info.get("url"):
        await query.edit_message_text(
            "⚠️ لینک صدا پیدا نشد." if lang == "fa" else "⚠️ Audio link not found."
        )
        return

    from bot.services.video_extractor import format_duration, format_filesize
    duration_str = format_duration(audio_info.get("duration"))
    size_str = format_filesize(audio_info.get("filesize_mb"))

    title_short = audio_info["title"][:60]
    ext = audio_info.get("ext", "m4a")
    audio_url = audio_info["url"]
    dur = f"⏱ {duration_str}" if duration_str else ""
    sz = f"  · {size_str}" if size_str else ""

    if lang == "fa":
        text = (
            f"🎵 <b>{title_short}</b>\n"
            f"{dur}{sz}\n\n"
            f"🔗 <a href='{audio_url}'>لینک مستقیم صدا ({ext})</a>\n\n"
            f"⏰ این لینک حدود ۶ ساعت معتبره.\n"
            f"💡 توی مرورگر یا دانلود منیجر باز کن."
        )
    else:
        text = (
            f"🎵 <b>{title_short}</b>\n"
            f"{dur}{sz}\n\n"
            f"🔗 <a href='{audio_url}'>Direct Audio Link ({ext})</a>\n\n"
            f"⏰ Valid for ~6 hours.\n"
            f"💡 Open in browser or download manager."
        )

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
    )


def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(
        show_quality_selection, pattern=r"^vq:"
    ))
    app.add_handler(CallbackQueryHandler(
        send_quality_link, pattern=r"^vlink:"
    ))
    app.add_handler(CallbackQueryHandler(
        start_file_download, pattern=r"^vdl:"
    ))
    app.add_handler(CallbackQueryHandler(
        download_file_quality, pattern=r"^vdlq:"
    ))
    app.add_handler(CallbackQueryHandler(
        send_audio_link, pattern=r"^vaudio:"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: u.callback_query.answer(),
        pattern=r"^video:cancel"
    ))
    logger.info("Video handlers registered.")
