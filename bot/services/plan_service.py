"""
SocialtoFeed — Plan Service v3.1
Dynamic feature access from DB. Redis-cached 60s.
Admin credit system. Grace period 48h. Upsell logic.
"""
from __future__ import annotations
import json, logging
from typing import Any
from bot.models import Platform, PlanType, User

logger = logging.getLogger(__name__)
from bot.cache import get_redis  # PERF-4: shared pool instead of private client

async def get_plan_features(plan: PlanType) -> dict:
    cache_key = f"plan_features:{plan.value}"
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached: return json.loads(cached)
    except Exception: pass
    try:
        from bot.database import get_session
        from bot.models import PlanConfig
        from sqlalchemy import select
        async with get_session() as session:
            cfg = (await session.execute(
                select(PlanConfig).where(PlanConfig.plan == plan)
            )).scalar_one_or_none()
            if cfg and cfg.features_json:
                try:
                    r = await get_redis()
                    await r.setex(cache_key, 60, json.dumps(cfg.features_json))
                except Exception: pass
                return cfg.features_json
    except Exception as e:
        logger.warning(f"DB plan features failed: {e}")
    from config.settings import DEFAULT_PLAN_FEATURES
    return DEFAULT_PLAN_FEATURES.get(plan.value, DEFAULT_PLAN_FEATURES["free"])

async def get_user_features(user: User) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if user.credit_expires_at and user.credit_expires_at > now and user.credit_plan:
        return await get_plan_features(user.credit_plan)
    if user.grace_until and user.grace_until > now and user.original_plan_before_grace:
        return await get_plan_features(user.original_plan_before_grace)
    return await get_plan_features(user.plan)

async def feature(user: User, key: str, default: Any = False) -> Any:
    return (await get_user_features(user)).get(key, default)

async def get_user_platforms(user: User) -> list[Platform]:
    allowed = (await get_user_features(user)).get("platforms", [])
    result = []
    for p in allowed:
        try: result.append(Platform(p))
        except ValueError: pass
    return result

async def is_platform_allowed(platform: Platform, user: User) -> bool:
    allowed = (await get_user_features(user)).get("platforms", [])
    return platform.value in allowed

async def can_download_link(user: User) -> bool: return await feature(user,"download_link",False)
async def can_download_file(user: User) -> bool: return await feature(user,"download_file",False)
async def can_audio_link(user: User) -> bool: return await feature(user,"audio_link",False)
async def can_audio_file(user: User) -> bool: return await feature(user,"audio_file",False)
async def can_ai(user: User) -> bool: return await feature(user,"ai_summary",False)
async def can_fetch_on_demand(user: User) -> bool: return await feature(user,"fetch_on_demand",False)
async def get_bookmark_limit(user: User) -> int:
    """v3.3: Bookmarks are unlimited for all plans. Returns 0 = no cap."""
    return 0
async def get_ticket_limit(user: User) -> int: return await feature(user,"ticket_limit",1)
async def get_max_accounts(user: User) -> int: return (await get_user_features(user)).get("max_accounts",5)
async def get_upsell_interval(user: User) -> int: return await feature(user,"upsell_every_n_posts",0)
async def get_download_qualities(user: User) -> list: return await feature(user,"download_link_qualities",[])

async def grant_credit(user_id: int, plan: PlanType, days: int,
                       granted_by: str, reason: str = "") -> dict:
    """Grant admin credit — no payment required."""
    from datetime import datetime, timedelta, timezone
    from bot.database import get_session
    from bot.models import User, AdminCreditLog
    from sqlalchemy import select
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if not user: return {"success": False, "error": "User not found"}
        user.credit_plan = plan
        user.credit_expires_at = expires_at
        user.credit_granted_by = granted_by
        log = AdminCreditLog(
            user_id=user_id, plan=plan, days=days,
            reason=reason or f"Admin grant by {granted_by}",
            granted_by=granted_by, granted_at=now, expires_at=expires_at,
        )
        session.add(log)
        tg_id = user.telegram_id; lang = user.language
    pnames = {"fa":{"pro":"⭐️ پرو","premium":"💎 پریمیوم"},
              "en":{"pro":"⭐️ Pro","premium":"💎 Premium"}}
    pn = pnames.get(lang,pnames["en"]).get(plan.value, plan.value.title())
    exp = expires_at.strftime("%Y-%m-%d")
    msg = (f"🎁 <b>{'اشتراک رایگان فعال شد' if lang=='fa' else 'Free subscription activated'}!</b>\n\n"
           f"{'پلن' if lang=='fa' else 'Plan'}: <b>{pn}</b>\n"
           f"{'مدت' if lang=='fa' else 'Duration'}: <b>{days} {'روز' if lang=='fa' else 'days'}</b>\n"
           f"{'انقضا' if lang=='fa' else 'Expires'}: <b>{exp}</b>\n\n"
           f"{'از طرف تیم' if lang=='fa' else 'From'} AiSocialFeed.com 🚀")
    from bot.utils.telegram_utils import safe_send_message
    await safe_send_message(tg_id, msg, parse_mode="HTML")
    logger.info(f"Credit granted: user={user_id} plan={plan.value} days={days} by={granted_by}")
    return {"success": True, "user_id": user_id, "plan": plan.value, "days": days, "expires_at": exp}

async def revoke_credit(user_id: int, revoked_by: str) -> bool:
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if not user: return False
        user.credit_plan = None
        user.credit_expires_at = None
        user.credit_granted_by = None
    logger.info(f"Credit revoked: user={user_id} by={revoked_by}")
    return True

async def apply_grace_period(user_id: int) -> None:
    """48-hour grace period when subscription expires."""
    from datetime import datetime, timedelta, timezone
    from bot.database import get_session
    from bot.models import User
    from sqlalchemy import select
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if not user or user.plan == PlanType.FREE: return
        user.original_plan_before_grace = user.plan
        user.grace_until = now + timedelta(hours=48)
        await session.commit()
    logger.info(f"Grace period applied: user={user_id}")

async def should_show_upsell(user: User, post_count: int) -> bool:
    interval = await get_upsell_interval(user)
    if not interval: return False
    return post_count > 0 and post_count % interval == 0

def build_upsell_message(lang: str, current_plan: str) -> str:
    if current_plan == "free":
        if lang == "fa":
            return ("✨ <b>میخوای بیشتر داشته باشی؟</b>\n\n"
                    "با <b>پلن پرو ⭐️</b> — ماهی فقط $6:\n"
                    "• ۴۰ اکانت از ۱۰ پلتفرم\n• لینک دانلود ویدیو\n• Audio\n\n👉 /subscription")
        return ("✨ <b>Want more?</b>\n\nWith <b>Pro ⭐️</b> — $6/month:\n"
                "• 40 accounts, 10 platforms\n• Video download links\n• Audio\n\n👉 /subscription")
    if lang == "fa":
        return ("💎 <b>سطح بالاتر؟</b>\n\nبا <b>پریمیوم 💎</b> — ماهی $10:\n"
                "• ۱۰۰ اکانت از ۱۳ پلتفرم\n• AI نامحدود\n• دانلود فایل\n• Facebook+Discord\n\n👉 /subscription")
    return ("💎 <b>Level up?</b>\n\nWith <b>Premium 💎</b> — $10/month:\n"
            "• 100 accounts, 13 platforms\n• Unlimited AI\n• File downloads\n• Facebook+Discord\n\n👉 /subscription")
