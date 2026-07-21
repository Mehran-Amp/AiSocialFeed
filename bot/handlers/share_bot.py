"""SocialtoFeed — Share Bot Handler v3.1
3 times in first 3 weeks, 1/week, native language."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from bot.utils.keyboards import share_bot_keyboard
logger = logging.getLogger(__name__)

MAX_PROMPTS = 3
INTERVAL_DAYS = 7

_MSGS = {
    "fa":"😊 از ربات لذت میبری؟\n\n<b>AiSocialFeed.com</b>\n• 📱 دریافت خودکار از ۱۳ پلتفرم\n• 🤖 هوش مصنوعی\n• ⬇️ دانلود ویدیو\n• 🆓 رایگان\n\nبه دوستات معرفی کن! 🚀",
    "en":"😊 Enjoying the bot?\n\n<b>AiSocialFeed.com</b>\n• 📱 Auto-posts from 13 platforms\n• 🤖 AI summary & translate\n• ⬇️ Video downloads\n• 🆓 Free to start\n\nShare with friends! 🚀",
    "ar":"😊 هل تستمتع بالبوت؟\n\n<b>AiSocialFeed.com</b>\n• 📱 ١٣ منصة\n• 🤖 ذكاء اصطناعي\n• ⬇️ تحميل فيديو\n\nشارك مع أصدقائك! 🚀",
    "zh":"😊 喜欢这个机器人吗？\n\n<b>AiSocialFeed.com</b>\n• 📱 13个平台\n• 🤖 AI摘要翻译\n• ⬇️ 视频下载\n\n分享给朋友！🚀",
    "ru":"😊 Нравится бот?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 платформ\n• 🤖 ИИ\n• ⬇️ Скачать видео\n\nПоделись с друзьями! 🚀",
    "de":"😊 Macht der Bot Spaß?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 Plattformen\n• 🤖 KI\n• ⬇️ Video-Download\n\nTeile mit Freunden! 🚀",
    "tr":"😊 Botu beğeniyor musun?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 platform\n• 🤖 AI\n• ⬇️ Video indir\n\nArkadaşlarınla paylaş! 🚀",
    "es":"😊 ¿Disfrutando el bot?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 plataformas\n• 🤖 IA\n• ⬇️ Descargar video\n\n¡Comparte con amigos! 🚀",
    "fr":"😊 Tu aimes le bot?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 plateformes\n• 🤖 IA\n• ⬇️ Télécharger vidéo\n\nPartage avec tes amis! 🚀",
    "it":"😊 Ti piace il bot?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 piattaforme\n• 🤖 AI\n• ⬇️ Download video\n\nCondividi con gli amici! 🚀",
    "pt":"😊 Curtindo o bot?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 plataformas\n• 🤖 IA\n• ⬇️ Download de vídeo\n\nCompartilhe com amigos! 🚀",
    "hi":"😊 बॉट पसंद आ रहा है?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 प्लेटफॉर्म\n• 🤖 AI\n• ⬇️ वीडियो डाउनलोड\n\nदोस्तों के साथ शेयर करें! 🚀",
    "id":"😊 Suka dengan botnya?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 platform\n• 🤖 AI\n• ⬇️ Unduh video\n\nBagikan ke teman! 🚀",
    "ko":"😊 봇이 마음에 드시나요?\n\n<b>AiSocialFeed.com</b>\n• 📱 13개 플랫폼\n• 🤖 AI\n• ⬇️ 동영상 다운로드\n\n친구들에게 공유하세요! 🚀",
    "vi":"😊 Thích bot không?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 nền tảng\n• 🤖 AI\n• ⬇️ Tải video\n\nChia sẻ với bạn bè! 🚀",
    "th":"😊 ชอบบอทไหม?\n\n<b>AiSocialFeed.com</b>\n• 📱 13 แพลตฟอร์ม\n• 🤖 AI\n• ⬇️ ดาวน์โหลดวิดีโอ\n\nแชร์ให้เพื่อน! 🚀",
    "ku":"😊 ئایا بۆتەکە باشتە?\n\n<b>AiSocialFeed.com</b>\n• 📱 ١٣ پلاتفۆرم\n• 🤖 AI\n• ⬇️ داونلۆدی ڤیدیۆ\n\nبە هاوڕێکانت پێشکەش بکە! 🚀",
    "bn":"😊 বট পছন্দ হচ্ছে?\n\n<b>AiSocialFeed.com</b>\n• 📱 ১৩টি প্ল্যাটফর্ম\n• 🤖 AI\n• ⬇️ ভিডিও ডাউনলোড\n\nবন্ধুদের সাথে শেয়ার করুন! 🚀",
}

async def maybe_show_share_prompt(update, context, user) -> bool:
    now = datetime.now(timezone.utc)
    if (user.share_prompt_count or 0) >= MAX_PROMPTS: return False
    if user.created_at and (now - user.created_at).days > 21: return False
    if user.share_prompt_last_at and (now - user.share_prompt_last_at).days < INTERVAL_DAYS: return False
    from config import config
    ref = f"https://t.me/{config.app.bot_username}?start=ref_{user.telegram_id}"
    lang = user.language
    msg = _MSGS.get(lang, _MSGS["en"])
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML,
        reply_markup=share_bot_keyboard(lang, ref), disable_web_page_preview=True)
    try:
        from bot.database import get_session
        from bot.models import User as U
        from sqlalchemy import select
        async with get_session() as session:
            db_u=(await session.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db_u:
                db_u.share_prompt_count=(db_u.share_prompt_count or 0)+1
                db_u.share_prompt_last_at=now
    except Exception as e: logger.warning(f"Share prompt update failed: {e}")
    return True

async def cb_share_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer()
    user = context.user_data.get("user")
    if not user: return
    try:
        from bot.database import get_session
        from bot.models import User as U
        from sqlalchemy import select
        async with get_session() as session:
            db_u=(await session.execute(select(U).where(U.id==user.id))).scalar_one_or_none()
            if db_u: db_u.share_prompt_count = MAX_PROMPTS
    except Exception: pass
    await query.edit_message_text("👍" + (" باشه!" if user.language=="fa" else " Got it!"))

def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(cb_share_dismiss, pattern=r"^share:dismiss$"))
    logger.info("Share bot handler registered.")
