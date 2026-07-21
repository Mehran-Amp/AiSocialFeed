"""
SocialtoFeed — Support Handler
AI Q&A (before tickets), ticket creation and tracking.
"""

from __future__ import annotations

import logging
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
    PlanType, SupportTicket, TicketMessage, TicketStatus, TicketSubject, User,
)
from bot.utils.keyboards import main_menu, ticket_subjects
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t

logger = logging.getLogger(__name__)

# Conversation states
WAITING_AI_QUESTION = 30
WAITING_TICKET_TEXT = 31
WAITING_TICKET_ATTACHMENT = 32

PLAN_TICKET_LIMITS = {
    PlanType.FREE: 1,      # 1 ticket for free users
    PlanType.PRO: 2,
    PlanType.PREMIUM: 3,
}


# ─────────────────────────────────────────────
#  Support Menu
# ─────────────────────────────────────────────

async def show_support_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
) -> None:
    lang     = user.language
    plan_str = user.plan.value if hasattr(user.plan, "value") else str(user.plan)

    # v4.2: Help menu replaces standalone Support menu (tickets moved into Help)
    from bot.utils.keyboards import help_menu
    await update.message.reply_text(
        t("support.header", lang),
        parse_mode=ParseMode.HTML,
        reply_markup=help_menu(lang, plan_str),
    )


# ─────────────────────────────────────────────
#  Support Callbacks
# ─────────────────────────────────────────────

async def cb_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    parts = query.data.split(":")
    action = parts[1]

    if action == "menu":
        plan_str = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        from bot.utils.keyboards import help_menu
        await query.edit_message_text(
            t("support.header", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=help_menu(lang, plan_str),
        )
        return ConversationHandler.END

    elif action == "ask_ai":
        # Req #14: AI support is premium-only
        if user.plan != PlanType.PREMIUM:
            await query.edit_message_text(
                t("errors.plan_required", lang, plan="Premium 💎"),
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END
        await query.edit_message_text(t("support.ai_prompt", lang))
        return WAITING_AI_QUESTION

    elif action == "open_ticket":
        # Check ticket limit
        limit = PLAN_TICKET_LIMITS.get(user.plan, 0)
        if limit == 0:
            await query.edit_message_text(t("support.free_users", lang), parse_mode=ParseMode.HTML)
            return ConversationHandler.END

        async with get_session() as session:
            from sqlalchemy import select, func
            open_count = (await session.execute(
                select(func.count()).select_from(SupportTicket)
                .where(
                    SupportTicket.user_id == user.id,
                    SupportTicket.status != TicketStatus.CLOSED,
                )
            )).scalar() or 0

        if open_count >= limit:
            await query.edit_message_text(
                t("support.ticket_limit", lang, limit=limit),
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END

        await query.edit_message_text(
            t("support.ticket_select_subject", lang),
            reply_markup=ticket_subjects(lang),
        )
        return ConversationHandler.END

    elif action == "my_tickets":
        await _show_my_tickets(query, user)
        return ConversationHandler.END

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  AI Q&A
# ─────────────────────────────────────────────

async def receive_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    question = update.message.text.strip()

    thinking_msg = await safe_send_message(
        update.effective_user.id,
        t("support.ai_thinking", lang),
    )

    try:
        from bot.services.ai_service import AIService
        answer = await AIService.answer_question(question, lang=lang)
    except Exception as e:
        logger.error(f"AI Q&A failed: {e}")
        answer = None

    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    if not answer:
        answer = t("errors.ai_unavailable", lang)

    # Show answer with option to open ticket
    buttons = [
        [InlineKeyboardButton(
            "✅ Got it",
            callback_data="support:menu"
        )],
        [InlineKeyboardButton(
            "📝 Still need help — open ticket",
            callback_data="support:open_ticket"
        )],
    ]

    await safe_send_message(
        update.effective_user.id,
        f"🤖 <b>AI Answer:</b>\n\n{answer}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Ticket Creation
# ─────────────────────────────────────────────

async def cb_ticket_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    subject_value = query.data.split(":")[-1]

    try:
        subject = TicketSubject(subject_value)
    except ValueError:
        return ConversationHandler.END

    context.user_data["ticket_subject"] = subject

    await query.edit_message_text(
        t("support.ticket_write", lang),
        parse_mode=ParseMode.HTML,
    )
    return WAITING_TICKET_TEXT


async def receive_ticket_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    text = update.message.text.strip()
    context.user_data["ticket_text"] = text

    await safe_send_message(
        update.effective_user.id,
        t("support.ticket_attach", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("support.ticket_skip_attach", lang), callback_data="ticket:skip_attach")]
        ]),
    )
    return WAITING_TICKET_ATTACHMENT


async def cb_skip_attach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _finalize_ticket(query.message, context, [], query.message.chat_id)


async def receive_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    attachments = context.user_data.get("ticket_attachments", [])

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        attachments.append({"type": "photo", "file_id": file_id})
    elif update.message.document:
        doc = update.message.document
        size_mb = doc.file_size / (1024 * 1024) if doc.file_size else 0
        if size_mb > 3:
            await safe_send_message(
                update.effective_user.id,
                "⚠️ File too large (max 3MB).",
            )
            return WAITING_TICKET_ATTACHMENT

        ext = (doc.file_name or "").split(".")[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "pdf"):
            await safe_send_message(
                update.effective_user.id, "⚠️ Only JPG, PNG, PDF allowed.",
            )
            return WAITING_TICKET_ATTACHMENT

        attachments.append({"type": "document", "file_id": doc.file_id, "name": doc.file_name})

    context.user_data["ticket_attachments"] = attachments

    if len(attachments) >= 2:
        return await _finalize_ticket(
            update.message, context, attachments, update.effective_user.id
        )

    await safe_send_message(
        update.effective_user.id,
        f"✅ File received ({len(attachments)}/2). Send another or:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Done", callback_data="ticket:skip_attach")]
        ]),
    )
    return WAITING_TICKET_ATTACHMENT


async def _finalize_ticket(message, context, attachments: list, chat_id: int) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    subject: TicketSubject = context.user_data.get("ticket_subject", TicketSubject.GENERAL)
    text: str = context.user_data.get("ticket_text", "")

    async with get_session() as session:
        ticket = SupportTicket(
            user_id=user.id,
            subject=subject,
            status=TicketStatus.OPEN,
        )
        session.add(ticket)
        await session.flush()

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_type="user",
            message=text,
            attachments=attachments,
        )
        session.add(msg)
        ticket_number = ticket.ticket_number

    await safe_send_message(
        chat_id,
        t("support.ticket_submitted", lang, number=ticket_number),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(lang),
    )

    # v3.2: route ticket notification through alerts.py → personal ID (CRITICAL)
    plan_str     = user.plan.value.upper() if hasattr(user.plan, "value") else str(user.plan).upper()
    username_str = f"@{user.username}" if getattr(user, "username", None) else "no username"
    subject_tag  = {"technical":"🔧","payment":"💳","general":"❓","report":"🚩"}.get(subject.value.lower(),"🎫")
    from bot.utils.alerts import alert_critical
    await alert_critical(
        f"{subject_tag} New Ticket #{ticket_number}",
        f"💬 {text[:400]}{'…' if len(text) > 400 else ''}",
        user=f"{user.telegram_id} {username_str}",
        plan=plan_str,
        subject=subject.value.replace("_", " ").title(),
    )

    # Cleanup
    for key in ("ticket_subject", "ticket_text", "ticket_attachments"):
        context.user_data.pop(key, None)

    return ConversationHandler.END


# ─────────────────────────────────────────────
#  My Tickets
# ─────────────────────────────────────────────

async def _show_my_tickets(query, user: User) -> None:
    lang = user.language

    async with get_session() as session:
        from sqlalchemy import select
        tickets = (await session.execute(
            select(SupportTicket)
            .where(
                SupportTicket.user_id == user.id,
                SupportTicket.status != TicketStatus.CLOSED,
            )
            .order_by(SupportTicket.created_at.desc())
        )).scalars().all()

    if not tickets:
        await query.edit_message_text(
            t("support.tickets_empty", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("menu.back", lang), callback_data="support:menu")]
            ]),
        )
        return

    buttons = []
    for ticket in tickets:
        status_icon = {"open": "🟡", "answered": "🟢", "closed": "⚫"}.get(ticket.status.value, "⚪")
        label = (
            f"{status_icon} {ticket.ticket_number} — "
            f"{ticket.subject.value} — "
            f"{ticket.created_at.strftime('%m/%d')}"
        )
        buttons.append([InlineKeyboardButton(label, callback_data=f"ticket:view:{ticket.id}")])

    buttons.append([InlineKeyboardButton(t("menu.back", lang), callback_data="support:menu")])

    await query.edit_message_text(
        f"📋 <b>Your Tickets</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

async def show_my_tickets(update, context, user):
    from bot.database import get_session
    from bot.utils.keyboards import back_button
    lang = user.language; fa = lang == "fa"
    try:
        async with get_session() as s:
            from sqlalchemy import select
            from bot.models import SupportTicket
            tickets = (await s.execute(
                select(SupportTicket).where(SupportTicket.user_id == user.id)
                .order_by(SupportTicket.created_at.desc()).limit(10)
            )).scalars().all()
        if not tickets:
            t1 = "تیکتی وجود ندارد." if fa else "No tickets found."
            txt = f"🎫 {t1}"
        else:
            rows = "\n".join(
                f"#{tk.ticket_number} — {tk.subject.value if hasattr(tk.subject,'value') else tk.subject} — {tk.status.value if hasattr(tk.status,'value') else tk.status}"
                for tk in tickets
            )
            t1 = "تیکت‌های من" if fa else "My Tickets"
            txt = f"🎫 <b>{t1}</b>\n\n{rows}"
    except Exception:
        txt = "🎫 Could not load tickets."
    query = update.callback_query
    if query:
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=back_button(lang, "profile:help"))
    else:
        from bot.utils.telegram_utils import safe_send_message
        await safe_send_message(update.effective_user.id, txt, parse_mode="HTML", reply_markup=back_button(lang, "profile:help"))


def register(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_support, pattern=r"^support:"),
            CallbackQueryHandler(cb_ticket_subject, pattern=r"^ticket:subject:"),
        ],
        states={
            WAITING_AI_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_question),
            ],
            WAITING_TICKET_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ticket_text),
            ],
            WAITING_TICKET_ATTACHMENT: [
                MessageHandler(
                    (filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
                    receive_attachment,
                ),
                CallbackQueryHandler(cb_skip_attach, pattern=r"^ticket:skip_attach"),
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    logger.info("Support handlers registered.")
