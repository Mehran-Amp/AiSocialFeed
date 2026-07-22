"""
SocialtoFeed — Developer Digest v3.2

Sends one structured summary message to ADMIN_CHANNEL_ID every 6 hours.
Replaces scattered individual notifications with a single actionable snapshot.

Sections:
  👥 Users      — new joins, active, plan distribution
  💰 Payments   — transactions last 6h, revenue
  🔌 Platforms  — circuit breaker states, fetch success rates
  ❌ Errors     — top 5 by frequency from SystemLog
  ⚙️ System     — queue depth, Redis memory, worker heartbeat
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from worker.tasks import celery_app, _run

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.digest.send_developer_digest")
def send_developer_digest() -> dict:
    return _run(_async_digest())


async def _async_digest() -> dict:
    from bot.database import init_db, get_session
    await init_db()

    from config.settings import config
    if not config.admin.channel_configured:
        logger.warning("[digest] ADMIN_CHANNEL_ID not set — skipping digest")
        return {"skipped": "no channel configured"}

    now  = datetime.now(timezone.utc)
    ago6 = now - timedelta(hours=6)
    ago24= now - timedelta(hours=24)

    sections = []

    # ── 👥 Users ──────────────────────────────────────────────────────────────
    try:
        async with get_session() as session:
            from sqlalchemy import select, func
            from bot.models import User, PlanType

            new_6h = (await session.execute(
                select(func.count()).select_from(User)
                .where(User.created_at >= ago6)
            )).scalar() or 0

            new_24h = (await session.execute(
                select(func.count()).select_from(User)
                .where(User.created_at >= ago24)
            )).scalar() or 0

            plan_counts = {}
            for plan in [PlanType.FREE, PlanType.PRO, PlanType.PREMIUM]:
                c = (await session.execute(
                    select(func.count()).select_from(User)
                    .where(User.plan == plan, User.is_banned == False)
                )).scalar() or 0
                plan_counts[plan.value] = c

            active_24h = (await session.execute(
                select(func.count()).select_from(User)
                .where(User.last_active_at >= ago24)
            )).scalar() or 0

        sections.append(
            f"👥 <b>Users</b>\n"
            f"  New (6h / 24h): <b>{new_6h}</b> / <b>{new_24h}</b>\n"
            f"  Active 24h: <b>{active_24h}</b>\n"
            f"  Free: {plan_counts.get('free',0)}  "
            f"Pro: {plan_counts.get('pro',0)}  "
            f"Premium: {plan_counts.get('premium',0)}"
        )
    except Exception as e:
        sections.append(f"👥 <b>Users</b>\n  ⚠️ Error: {e}")

    # ── 💰 Payments ───────────────────────────────────────────────────────────
    try:
        async with get_session() as session:
            from sqlalchemy import select, func
            from bot.models import Transaction, TransactionStatus

            paid_6h = (await session.execute(
                select(func.count()).select_from(Transaction)
                .where(
                    Transaction.created_at >= ago6,
                    Transaction.status == TransactionStatus.CONFIRMED,
                )
            )).scalar() or 0

            pending = (await session.execute(
                select(func.count()).select_from(Transaction)
                .where(Transaction.status == TransactionStatus.PENDING)
            )).scalar() or 0

        sections.append(
            f"💰 <b>Payments</b>\n"
            f"  Confirmed (6h): <b>{paid_6h}</b>\n"
            f"  Pending monitors: <b>{pending}</b>"
        )
    except Exception as e:
        sections.append(f"💰 <b>Payments</b>\n  ⚠️ Error: {e}")

    # ── 🔌 Platforms ──────────────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()
        cb_keys = await r.keys("cb:open:*")
        open_platforms = [k.split(":")[-1] for k in cb_keys]

        # Fetch success rates from tracking keys
        platform_lines = []
        from bot.models import Platform
        for plat in [p.value for p in Platform]:
            hour_key  = now.strftime(f"fetch:success:{plat}:%Y%m%d%H")
            fail_key  = now.strftime(f"fetch:fail:{plat}:%Y%m%d%H")
            ok  = int(await r.get(hour_key) or 0)
            err = int(await r.get(fail_key) or 0)
            total = ok + err
            if total > 0:
                rate = round(ok / total * 100)
                icon = "✅" if rate >= 90 else ("⚠️" if rate >= 70 else "❌")
                platform_lines.append(f"  {icon} {plat}: {rate}% ({total} fetches)")

        cb_text = (
            f"  🔴 Open circuits: {', '.join(open_platforms)}"
            if open_platforms else "  🟢 All circuits closed"
        )
        perf_text = "\n".join(platform_lines[:6]) if platform_lines else "  No fetch data yet"
        sections.append(f"🔌 <b>Platforms</b>\n{cb_text}\n{perf_text}")
    except Exception as e:
        sections.append(f"🔌 <b>Platforms</b>\n  ⚠️ Error: {e}")

    # ── ❌ Top Errors ──────────────────────────────────────────────────────────
    try:
        async with get_session() as session:
            from sqlalchemy import select, func
            from bot.models import SystemLog, LogLevel

            top_errors = (await session.execute(
                select(SystemLog.message, func.count().label("n"))
                .where(
                    SystemLog.level.in_([LogLevel.ERROR, LogLevel.CRITICAL]),
                    SystemLog.created_at >= ago6,
                )
                .group_by(SystemLog.message)
                .order_by(func.count().desc())
                .limit(5)
            )).all()

        if top_errors:
            error_lines = "\n".join(
                f"  {i+1}. [{row.n}×] {row.message[:60]}{'…' if len(row.message)>60 else ''}"
                for i, row in enumerate(top_errors)
            )
        else:
            error_lines = "  ✅ No errors in last 6h"
        sections.append(f"❌ <b>Top Errors (6h)</b>\n{error_lines}")
    except Exception as e:
        sections.append(f"❌ <b>Top Errors</b>\n  ⚠️ Error: {e}")

    # ── ⚙️ System ─────────────────────────────────────────────────────────────
    try:
        from bot.cache import get_redis
        r = await get_redis()

        # Redis memory
        info = await r.info("memory")
        mem_mb = round(info.get("used_memory", 0) / 1024 / 1024, 1)

        # Celery queue depth
        queue_depth = await r.llen("celery") or 0

        # Worker heartbeat
        hb_keys = await r.keys("celery:worker:heartbeat:*")
        worker_count = len(hb_keys)

        # Webhook last seen
        wh_key = now.strftime("webhook:success:%Y%m%d%H")
        wh_count = int(await r.get(wh_key) or 0)

        sections.append(
            f"⚙️ <b>System</b>\n"
            f"  Redis: <b>{mem_mb} MB</b>\n"
            f"  Celery queue: <b>{queue_depth}</b> tasks\n"
            f"  Workers alive: <b>{worker_count}</b>\n"
            f"  Webhook updates (1h): <b>{wh_count}</b>"
        )
    except Exception as e:
        sections.append(f"⚙️ <b>System</b>\n  ⚠️ Error: {e}")

    # ── Assemble and send ─────────────────────────────────────────────────────
    ts   = now.strftime("%Y-%m-%d %H:%M UTC")
    body = (
        f"📊 <b>AiSocialFeed — 6h Digest</b>\n"
        f"🕐 {ts}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(sections)
    )

    try:
        from bot.utils.telegram_utils import get_bot
        from telegram.constants import ParseMode
        bot = get_bot()
        await bot.send_message(
            chat_id=config.admin.admin_channel_id,
            text=body,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info("[digest] 6h developer digest sent to admin channel")
        return {"status": "sent", "sections": len(sections)}
    except Exception as e:
        logger.error(f"[digest] failed to send: {e}")
        return {"status": "error", "error": str(e)}
