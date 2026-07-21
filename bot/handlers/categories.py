"""
SocialtoFeed — Categories Handler
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
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
from bot.models import Category, PlanType, User
from bot.utils.keyboards import back_button, main_menu
from bot.utils.telegram_utils import safe_send_message
from bot.utils.translator import t
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

WAITING_CATEGORY_NAME = 10

PLAN_CATEGORY_LIMITS = {
    PlanType.FREE: 5,
    PlanType.PRO: 10,
    PlanType.PREMIUM: 20,
}

DEFAULT_CATEGORIES = [
    ("News", "📰"), ("Technology", "💻"), ("Sports", "⚽"),
    ("Entertainment", "🎬"), ("Friends", "👥"), ("Business", "💼"),
    ("Science", "🔬"), ("Fashion", "👗"),
]


async def show_categories(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
) -> None:
    lang = user.language

    async with get_session() as session:
        from sqlalchemy import select
        cats = (await session.execute(
            select(Category)
            .where(Category.user_id == user.id)
            .order_by(Category.sort_order, Category.name)
        )).scalars().all()

    limit = PLAN_CATEGORY_LIMITS.get(user.plan, 5)
    header = t("categories.header", lang, count=len(cats), limit=limit)

    buttons = []
    for cat in cats:
        emoji = cat.emoji or "📁"
        label = f"{emoji} {cat.name}"
        if cat.is_default:
            label += " 📌"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"cat:view:{cat.id}"),
        ])

    if len(cats) < limit:
        buttons.append([InlineKeyboardButton(
            t("categories.create", lang), callback_data="cat:create"
        )])
    buttons.append([InlineKeyboardButton(t("menu.back", lang), callback_data="menu:main")])

    await update.message.reply_text(
        header,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    lang = user.language
    parts = query.data.split(":")
    action = parts[1]

    if action == "create":
        limit = PLAN_CATEGORY_LIMITS.get(user.plan, 5)
        async with get_session() as session:
            from sqlalchemy import select, func
            count = (await session.execute(
                select(func.count()).select_from(Category)
                .where(Category.user_id == user.id)
            )).scalar()

        if count >= limit:
            await query.edit_message_text(
                t("categories.limit_reached", lang, limit=limit),
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END

        await query.edit_message_text(t("categories.name_prompt", lang))
        return WAITING_CATEGORY_NAME

    elif action == "view":
        cat_id = int(parts[2])
        async with get_session() as session:
            from sqlalchemy import select
            cat = (await session.execute(
                select(Category).where(
                    Category.id == cat_id,
                    Category.user_id == user.id,
                )
            )).scalar_one_or_none()

        if not cat:
            return ConversationHandler.END

        btns = []
        if not cat.is_default:
            btns.append([
                InlineKeyboardButton("✏️ Rename", callback_data=f"cat:rename:{cat_id}"),
                InlineKeyboardButton("🗑 Delete", callback_data=f"cat:delete:{cat_id}"),
            ])
        btns.append([InlineKeyboardButton(t("menu.back", lang), callback_data="cat:list")])

        emoji = cat.emoji or "📁"
        await query.edit_message_text(
            f"{emoji} <b>{cat.name}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(btns),
        )

    elif action == "delete":
        cat_id = int(parts[2])
        async with get_session() as session:
            from sqlalchemy import select
            cat = (await session.execute(
                select(Category).where(
                    Category.id == cat_id, Category.user_id == user.id
                )
            )).scalar_one_or_none()

            if not cat or cat.is_default:
                await query.answer(t("categories.cant_delete_default", lang), show_alert=True)
                return ConversationHandler.END

            # Move accounts to default category
            from bot.models import Account
            from sqlalchemy import update as sql_update
            default_cat = (await session.execute(
                select(Category).where(
                    Category.user_id == user.id, Category.is_default == True
                )
            )).scalar_one_or_none()

            if default_cat:
                await session.execute(
                    sql_update(Account)
                    .where(Account.category_id == cat_id)
                    .values(category_id=default_cat.id)
                )

            await session.delete(cat)

        await query.edit_message_text(
            t("categories.deleted", lang),
            parse_mode=ParseMode.HTML,
        )

    return ConversationHandler.END


async def receive_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user: Optional[User] = context.user_data.get("user")
    if not user:
        return ConversationHandler.END

    name = update.message.text.strip()[:64]
    lang = user.language

    async with get_session() as session:
        cat = Category(
            user_id=user.id,
            name=name,
            is_default=False,
        )
        session.add(cat)

    await safe_send_message(
        update.effective_user.id,
        t("categories.created", lang, name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(lang),
    )
    return ConversationHandler.END


def register(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_categories, pattern=r"^cat:")],
        states={
            WAITING_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_category_name)
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    logger.info("Category handlers registered.")
