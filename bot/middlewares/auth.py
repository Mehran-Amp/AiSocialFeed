"""
SocialtoFeed — Auth Middleware
Runs before every handler:
  - Creates user if first visit
  - Blocks banned users
  - Updates last_active_at
  - Injects user object into context
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.database import get_session
from bot.models import User, PlanType
from bot.utils.translator import t
from bot.utils.telegram_utils import safe_send_message

logger = logging.getLogger(__name__)


async def get_or_create_user(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> User:
    """
    Fetch user from DB or create on first visit.
    Also updates username/first_name if changed.
    """
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            # First visit — create user
            import secrets
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                plan=PlanType.FREE,
                language="en",
                # Fix #1: generate unique 8-char referral code at creation
                # so ?start=ref_<code> links work immediately
                referral_code=secrets.token_hex(4),
            )
            # Create default "General" category after user is saved
            session.add(user)
            await session.flush()  # get user.id

            from bot.models import Category
            default_cat = Category(
                user_id=user.id,
                name="General",
                emoji="📌",
                is_default=True,
                sort_order=0,
            )
            session.add(default_cat)
            logger.info(f"New user created: tg_id={telegram_id}")
            # v3.2: fire low-priority operational alert → admin channel
            import asyncio as _asyncio
            from bot.utils.alerts import alert_operational
            _asyncio.ensure_future(alert_operational(
                "New User Joined",
                alert_type="new_user_joined",
                telegram_id=telegram_id,
                username=f"@{username}" if username else "—",
            ))
        else:
            # Update mutable fields
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name

        user.last_active_at = datetime.now(timezone.utc)
        return user


def auth_middleware(func: Callable) -> Callable:
    """
    Decorator for handlers. Injects authenticated user into context.
    Blocks banned users. Updates activity timestamp.

    Usage:
        @auth_middleware
        async def my_handler(update, context):
            user: User = context.user_data["user"]
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_user = update.effective_user
        if tg_user is None:
            return  # ignore non-user updates

        # v3.2: set correlation ID for this update — every log line gets tagged
        # so a user complaint can be traced: search logs for "<telegram_id>:<rid>"
        import secrets
        rid = secrets.token_hex(4)
        from bot.utils.logger import set_request_id
        set_request_id(f"{tg_user.id}:{rid}")
        context.user_data["request_id"] = rid

        try:
            user = await get_or_create_user(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
        except Exception as e:
            logger.error(f"Auth middleware DB error for tg_id={tg_user.id}: {e}")
            await safe_send_message(tg_user.id, t("errors.generic"))
            return

        # Block banned users
        if user.is_banned:
            await safe_send_message(tg_user.id, t("errors.banned", lang=user.language))
            return

        # Inject user into handler context
        context.user_data["user"] = user

        return await func(update, context)

    wrapper.__name__ = func.__name__
    return wrapper


def require_admin(func: Callable) -> Callable:
    """
    Decorator that restricts handler to ADMIN_TELEGRAM_ID only.
    Silently ignores non-admin calls (no message sent — security best practice).

    Usage:
        @require_admin
        async def cmd_stats(update, context):
            ...
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from config import config
        tg_user = update.effective_user
        if tg_user is None or tg_user.id != config.telegram.admin_id:
            logger.warning(f"Unauthorized admin access attempt: tg_id={tg_user.id if tg_user else 'unknown'}")
            return
        return await func(update, context)

    wrapper.__name__ = func.__name__
    return wrapper


def require_plan(*plans: PlanType):
    """
    Decorator that requires a minimum plan.

    Usage:
        @require_plan(PlanType.PREMIUM)
        async def download_video(update, context):
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user: Optional[User] = context.user_data.get("user")
            if user is None:
                return

            if user.plan not in plans:
                plan_names = "/".join(p.value.capitalize() for p in plans)
                await safe_send_message(
                    update.effective_user.id,
                    t("errors.plan_required", lang=user.language, plan=plan_names),
                )
                return

            return await func(update, context)

        wrapper.__name__ = func.__name__
        return wrapper
    return decorator
