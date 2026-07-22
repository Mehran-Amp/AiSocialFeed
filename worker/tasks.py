"""
SocialtoFeed — Celery App & Tasks
All background tasks: fetching, digest, subscription, cleanup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery import Celery
from celery.signals import worker_process_init


@worker_process_init.connect
def _setup_db_on_worker_start(sender=None, **kwargs):
    """Run init_db() once per worker process, not per task."""
    from bot.database import init_db
    try:
        asyncio.run(init_db())
        # v3.2: write heartbeat key so health_check and digest can confirm worker is alive
        import redis as redis_lib
        from config import config as cfg
        r = redis_lib.from_url(cfg.redis.url, decode_responses=True)
        import socket
        hb_key = f"celery:worker:heartbeat:{socket.gethostname()}"
        r.set(hb_key, "1", ex=cfg.admin.worker_heartbeat_ttl)
        r.close()
    except Exception as e:
        logger.warning(f"init_db on worker start failed: {e}")

from celery.schedules import crontab

from config import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Celery App
# ─────────────────────────────────────────────

celery_app = Celery(
    "aisocialfeed",
    broker=config.redis.celery_broker,
    backend=config.redis.celery_backend,
    include=["worker.growth", "worker.infra", "worker.digest"],  # v3.2: add digest
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "worker.tasks.fetch_account_task":          {"queue": "platforms"},
        "worker.tasks.send_digest_task":            {"queue": "default"},
        "worker.tasks.download_video_task":         {"queue": "default"},
        "worker.tasks.check_subscriptions":         {"queue": "default"},
        "worker.tasks.cleanup_old_posts":           {"queue": "default"},
        "worker.tasks.check_platform_health":       {"queue": "default"},
        "worker.tasks.retry_pending_payments":      {"queue": "default"},
        "worker.tasks.check_anomalies_task":        {"queue": "default"},
        "worker.digest.send_developer_digest":      {"queue": "default"},  # v3.2
        "worker.infra.check_webhook_health":        {"queue": "default"},  # v3.2
    },
    beat_schedule={
        # Fetch all active accounts every 15 minutes
        "schedule-fetches": {
            "task": "worker.tasks.schedule_pending_fetches",
            "schedule": crontab(minute="*/15"),
        },
        # Send scheduled digests every hour
        "send-digests": {
            "task": "worker.tasks.send_due_digests",
            "schedule": crontab(minute=0),  # top of every hour
        },
        # Check expiring subscriptions daily at 9 AM
        "check-subscriptions": {
            "task": "worker.tasks.check_subscriptions",
            "schedule": crontab(hour=9, minute=0),
        },
        # Cleanup old sent_posts weekly
        "cleanup-posts": {
            "task": "worker.tasks.cleanup_old_posts",
            "schedule": crontab(hour=3, minute=0),  # Daily 3AM UTC
        },
        # Platform health check every 15 min
        "platform-health": {
            "task": "worker.tasks.check_platform_health",
            "schedule": crontab(minute="*/15"),
        },

        # Re-engage inactive users daily 11 AM
        "reengage-inactive": {
            "task": "worker.growth.reengage_inactive",
            "schedule": crontab(hour=11, minute=0),
        },
        # Cleanup downloaded videos every hour
        "cleanup-downloads": {
            "task": "worker.growth.cleanup_downloads",
            "schedule": crontab(minute=0),
        },
        # Daily backup to Telegram channel at 03:00 UTC
        "daily-backup": {
            "task": "worker.infra.backup_to_telegram",
            "schedule": crontab(hour=3, minute=0),
        },
        # v3.2: developer digest every 6 hours to admin channel
        "developer-digest": {
            "task": "worker.digest.send_developer_digest",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # v3.2: webhook silence detector every 10 minutes
        "webhook-health": {
            "task": "worker.infra.check_webhook_health",
            "schedule": crontab(minute="*/10"),
        },
        # Anomaly Alert System — every 5 min push to admin if issues found
        "check-anomalies": {
            "task": "worker.tasks.check_anomalies_task",
            "schedule": crontab(minute="*/5"),
        },
        # Payment Retry Queue — every 5 min
        # Rechecks PENDING crypto txs >10 min old via CoinEx API directly.
        # Guards against webhook miss, bot downtime, network blips.
        "retry-pending-payments": {
            "task": "worker.tasks.retry_pending_payments",
            "schedule": crontab(minute="*/5"),
        },
    },
)


def _run(coro):
    """Run async coroutine in Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─────────────────────────────────────────────
#  Task: Fetch Single Account
# ─────────────────────────────────────────────

@celery_app.task(
    name="worker.tasks.fetch_account_task",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 min
)
def fetch_account_task(self, account_id: int) -> dict:
    """Fetch and deliver new posts for one account."""

    async def _fetch():
        from bot.database import init_db, get_session
        from bot.platforms.fetchers import get_fetcher
        from bot.models import Account, User, PlanType
        from sqlalchemy import select, update
        from config import config as cfg

        await init_db()

        async with get_session() as session:
            account = (await session.execute(
                select(Account).where(Account.id == account_id)
            )).scalar_one_or_none()

        if not account:
            return {"status": "not_found"}

        # Set next_fetch_at BEFORE fetching to prevent race condition.
        # If two workers pick up the same account, the second one will
        # see next_fetch_at already set and skip sending duplicate posts.
        # v4.2.1 issue-13: fallback chain is account override -> user's Premium
        # fetch_interval_minutes setting -> global platform default.
        interval = account.custom_interval_minutes
        if interval is None:
            async with get_session() as session:
                owner = (await session.execute(
                    select(User).where(User.id == account.user_id)
                )).scalar_one_or_none()
            if owner and owner.plan == PlanType.PREMIUM and owner.fetch_interval_minutes:
                interval = owner.fetch_interval_minutes
            else:
                interval = cfg.platform.default_fetch_interval
        next_run = datetime.now(timezone.utc) + timedelta(minutes=interval)
        async with get_session() as session:
            await session.execute(
                update(Account)
                .where(Account.id == account_id)
                .values(next_fetch_at=next_run)
            )

        fetcher = get_fetcher(account.platform)
        delivered = await fetcher.run(account_id)

        return {"status": "ok", "delivered": delivered}

    try:
        return _run(_fetch())
    except Exception as exc:
        logger.error(f"fetch_account_task failed for account {account_id}: {exc}")
        raise self.retry(exc=exc)


# ─────────────────────────────────────────────
#  Task: Schedule All Pending Fetches
# ─────────────────────────────────────────────

@celery_app.task(name="worker.tasks.schedule_pending_fetches")
def schedule_pending_fetches() -> dict:
    """
    Find all accounts due for a fetch and dispatch individual tasks.
    Runs every 15 minutes via beat.

    SPREAD SCHEDULING:
    Tasks are spread evenly over 25 minutes instead of all firing at once.
    This prevents Celery queue flooding at high user counts.

    Example with 10,000 accounts:
      Before fix: 10,000 tasks in 1 second  -> server overload
      After fix:  ~7 tasks per second        -> server stable
    """

    async def _schedule():
        from bot.database import init_db, get_session
        from sqlalchemy import select
        from bot.models import Account

        await init_db()

        now = datetime.now(timezone.utc)

        # PERF-3 fix: cursor-based pagination so all accounts are covered over
        # successive beat cycles, even when active accounts exceed 5,000.
        import redis as redis_lib
        from config import config as cfg
        _r = redis_lib.from_url(cfg.redis.url, decode_responses=True)
        last_id = int(_r.get("scheduler:last_account_id") or 0)

        async with get_session() as session:
            due_accounts = (await session.execute(
                select(Account.id).where(
                    Account.is_active == True,
                    Account.next_fetch_at <= now,
                    Account.id > last_id,
                )
                .order_by(Account.id)
                .limit(5000)
            )).scalars().all()

        # If we hit the limit there may be more — advance cursor.
        # If fewer than 5000 returned, we've lapped the table — reset cursor.
        if len(due_accounts) == 5000:
            _r.set("scheduler:last_account_id", due_accounts[-1], ex=3600)
        else:
            _r.delete("scheduler:last_account_id")  # reset for next cycle
        # No _r.close() needed — ConnectionPool reclaims the connection automatically

        total = len(due_accounts)
        if total == 0:
            return {"scheduled": 0}

        # Spread window: 25 minutes = 1,500 seconds
        # Small loads (<50 accounts) fire immediately - no need to spread
        SPREAD_WINDOW = 25 * 60  # seconds

        for i, acc_id in enumerate(due_accounts):
            if total <= 50:
                delay = 0  # small load - fire immediately
            else:
                delay = int((i / total) * SPREAD_WINDOW)

            fetch_account_task.apply_async(
                args=[acc_id],
                queue="platforms",
                countdown=delay,
            )

        spread_info = "immediate" if total <= 50 else f"spread over 25 min"
        logger.info(f"Scheduled {total} account fetches ({spread_info}).")
        return {"scheduled": total, "spread": total > 50}

    return _run(_schedule())


# ─────────────────────────────────────────────
#  Task: Video Download
# ─────────────────────────────────────────────

@celery_app.task(
    name="worker.tasks.download_video_task",
    bind=True,
    max_retries=1,
    time_limit=360,   # 6 min hard kill
    soft_time_limit=300,  # 5 min soft
)
def download_video_task(self, user_telegram_id: int, url: str, quality: str = "720p") -> dict:
    """Download a video and send to user. Premium only."""

    async def _download():
        import os
        import yt_dlp
        from bot.utils.telegram_utils import get_bot, safe_send_message
        from bot.utils.translator import t
        from config import config as cfg

        os.makedirs(cfg.download.output_dir, exist_ok=True)

        # Map quality to yt-dlp format
        format_map = {
            "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
            "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "1080p": None,  # Always send direct link for 1080p
        }

        if quality == "1080p":
            await safe_send_message(
                user_telegram_id,
                t("post.download_link", "en") + f"\n{url}",
                parse_mode="HTML",
            )
            return {"status": "link_sent"}

        fmt = format_map.get(quality, format_map["720p"])
        output_path = os.path.join(cfg.download.output_dir, f"%(id)s.%(ext)s")

        ydl_opts = {
            "format": fmt,
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": cfg.download.max_filesize_mb * 1024 * 1024,
            "socket_timeout": 30,
        }

        bot = get_bot()
        downloaded_path = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_path = ydl.prepare_filename(info)

            if not os.path.exists(downloaded_path):
                raise FileNotFoundError(f"Downloaded file not found: {downloaded_path}")

            file_size_mb = os.path.getsize(downloaded_path) / (1024 * 1024)

            if file_size_mb > cfg.download.max_filesize_mb:
                # File too large — send direct link
                await safe_send_message(
                    user_telegram_id,
                    t("post.download_link", "en") + f"\n{url}",
                )
                return {"status": "link_sent", "reason": "too_large"}

            # Send video
            with open(downloaded_path, "rb") as f:
                await bot.send_video(
                    chat_id=user_telegram_id,
                    video=f,
                    caption=t("post.download_ready", "en"),
                    supports_streaming=True,
                )

            return {"status": "ok", "size_mb": round(file_size_mb, 1)}

        except yt_dlp.utils.DownloadError as e:
            # Send direct link as fallback
            await safe_send_message(
                user_telegram_id,
                t("post.download_link", "en") + f"\n{url}",
            )
            return {"status": "fallback_link", "error": str(e)}

        finally:
            # Cleanup downloaded file
            if downloaded_path and os.path.exists(downloaded_path):
                os.remove(downloaded_path)

    try:
        return _run(_download())
    except Exception as exc:
        logger.error(f"download_video_task failed: {exc}")
        return {"status": "error", "error": str(exc)}


# ─────────────────────────────────────────────
#  Task: Send Due Digests
# ─────────────────────────────────────────────

@celery_app.task(name="worker.tasks.send_due_digests")
def send_due_digests() -> dict:
    """Send digest summaries to users whose digest time has come."""

    async def _send():
        from bot.database import init_db, get_session
        from sqlalchemy import select
        from bot.models import User, PlanType

        await init_db()
        now = datetime.now(timezone.utc)

        async with get_session() as session:
            due_users = (await session.execute(
                select(User).where(
                    User.digest_enabled == True,
                    User.plan == PlanType.PREMIUM,
                    User.digest_next_send <= now,
                    User.is_banned == False,
                )
            )).scalars().all()

        sent = 0
        for user in due_users:
            try:
                from bot.services.digest_service import generate_digest
                from bot.utils.telegram_utils import safe_send_message

                text = await generate_digest(user.id, user.language, user.digest_interval_hours or 24)
                if text:
                    target = user.channel_forward_id or user.telegram_id
                    await safe_send_message(target, text, parse_mode="HTML")
                    sent += 1

                # Schedule next digest
                async with get_session() as s2:
                    from sqlalchemy import select as sel
                    from bot.models import User as U
                    u = (await s2.execute(sel(U).where(U.id == user.id))).scalar_one()
                    u.digest_next_send = now + timedelta(hours=u.digest_interval_hours or 24)

            except Exception as e:
                logger.error(f"Digest failed for user {user.id}: {e}")

        return {"sent": sent}

    return _run(_send())


# ─────────────────────────────────────────────
#  Task: Check Subscriptions
# ─────────────────────────────────────────────

@celery_app.task(name="worker.tasks.check_subscriptions")
def check_subscriptions() -> dict:
    """Send expiry warnings and downgrade expired subscriptions."""

    async def _check():
        from bot.database import init_db, get_session
        from sqlalchemy import select
        from bot.models import User, PlanType
        from bot.utils.telegram_utils import safe_send_message
        from bot.utils.translator import t
        from config import config as cfg

        await init_db()  # INC-4 fix: was the only task missing this call
        now = datetime.now(timezone.utc)
        warned = expired = 0

        # Stream results — avoids loading all paying users into memory at once
        async with get_session() as session:
            stream = await session.stream(
                select(User).where(
                    User.plan.in_([PlanType.PRO, PlanType.PREMIUM]),
                    User.subscription_expires_at.isnot(None),
                    User.is_banned == False,
                ).execution_options(yield_per=100)
            )
            paying_users = [u async for u in stream.scalars()]

        for user in paying_users:
            days_left = int((user.subscription_expires_at - now).total_seconds() / 86400)

            # Expiry warnings
            for warn_days in cfg.rate_limit.expiry_warn_days:
                if days_left == warn_days:
                    last_warn = user.last_expiry_warning_at
                    if not last_warn or (now - last_warn).days >= 1:
                        await safe_send_message(
                            user.telegram_id,
                            t("subscription.expiry_warning",
                              user.language, days=days_left),
                            parse_mode="HTML",
                        )
                        async with get_session() as s:
                            from sqlalchemy import select as sel
                            from bot.models import User as U
                            u = (await s.execute(
                                sel(U).where(U.id == user.id)
                            )).scalar_one()
                            u.last_expiry_warning_at = now
                        warned += 1

            # Expired — apply 48h grace period first, then hard downgrade
            if days_left < 0:
                # INC-2 fix: apply_grace_period() was defined but never called.
                # Give the user a 48-hour window before wiping their plan.
                # If they are already in grace, or grace has expired, downgrade.
                grace_active = (
                    user.grace_until
                    and user.grace_until > now
                    and user.original_plan_before_grace
                )
                grace_expired = (
                    user.grace_until
                    and user.grace_until <= now
                )

                if not user.grace_until and not grace_expired:
                    # First time we detect expiry — start grace period
                    from bot.services.plan_service import apply_grace_period
                    await apply_grace_period(user.id)
                    await safe_send_message(
                        user.telegram_id,
                        t("subscription.grace_started", user.language),
                        parse_mode="HTML",
                    )
                    continue  # check again next cycle

                if grace_active:
                    continue  # still within 48h grace — do nothing

                # Grace expired or no grace left — hard downgrade to free
                async with get_session() as s:
                    from sqlalchemy import select as sel
                    from bot.models import User as U, Account
                    u = (await s.execute(
                        sel(U).where(U.id == user.id)
                    )).scalar_one()
                    u.plan = PlanType.FREE
                    u.subscription_expires_at = None

                    # Disable accounts beyond free limit (5 + referral bonus)
                    from bot.models import PlanConfig
                    free_cfg = (await s.execute(
                        sel(PlanConfig).where(PlanConfig.plan == PlanType.FREE)
                    )).scalar_one_or_none()
                    free_limit = (free_cfg.max_accounts if free_cfg else 5) + u.referral_bonus_accounts

                    all_accounts = (await s.execute(
                        sel(Account)
                        .where(Account.user_id == user.id, Account.is_active == True)
                        .order_by(Account.created_at.desc())
                    )).scalars().all()

                    for acc in all_accounts[free_limit:]:
                        acc.is_active = False

                await safe_send_message(
                    user.telegram_id,
                    t("subscription.expired", user.language),
                    parse_mode="HTML",
                )
                expired += 1

        return {"warned": warned, "expired": expired}

    return _run(_check())


# ─────────────────────────────────────────────
#  Task: Cleanup Old Posts
# ─────────────────────────────────────────────

@celery_app.task(name="worker.tasks.cleanup_old_posts")
def cleanup_old_posts() -> dict:
    """Delete sent_posts older than dedup_window_days."""

    async def _cleanup():
        from bot.database import init_db, get_session
        from sqlalchemy import delete
        from bot.models import SentPost
        from config import config as cfg

        await init_db()
        cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.app.dedup_window_days)

        async with get_session() as session:
            result = await session.execute(
                delete(SentPost).where(SentPost.sent_at < cutoff)
            )
            deleted = result.rowcount

        # Also cleanup old system logs
        from bot.models import SystemLog
        log_cutoff = datetime.now(timezone.utc) - timedelta(
            days=cfg.logging.db_log_retention_days
        )
        async with get_session() as session:
            log_result = await session.execute(
                delete(SystemLog).where(SystemLog.created_at < log_cutoff)
            )
            log_deleted = log_result.rowcount

        logger.info(f"Cleanup: {deleted} posts, {log_deleted} logs deleted.")
        return {"posts_deleted": deleted, "logs_deleted": log_deleted}

    return _run(_cleanup())


# ─────────────────────────────────────────────
#  Task: Platform Health Check
# ─────────────────────────────────────────────

@celery_app.task(name="worker.tasks.check_platform_health")
def check_platform_health() -> dict:
    """
    Check health of RSSHub instance and RSS Bridge instances.
    Updates Redis cache. Alerts admin if RSSHub is down.
    """

    async def _health():
        import httpx
        import json
        from bot.cache import get_redis  # PERF-4: shared pool
        from config import config as cfg

        r = await get_redis()

        # ── Check RSSHub (primary source for Twitter/Instagram/TikTok/Threads/Facebook/Discord)
        rsshub_healthy = False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{cfg.rsshub.url}/healthz")
                rsshub_healthy = resp.status_code == 200
        except Exception as e:
            logger.warning(f"RSSHub health check failed: {e}")

        await r.setex(
            "rsshub_healthy",
            cfg.redis.rsshub_health_ttl,
            json.dumps({"healthy": rsshub_healthy, "url": cfg.rsshub.url}),
        )

        # ── Check RSS Bridge instances (kept for any remaining edge cases)
        healthy_bridge = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for instance in cfg.platform.rssbridge_instances:
                try:
                    resp = await client.get(instance)
                    if resp.status_code == 200:
                        healthy_bridge.append(instance)
                except Exception:
                    logger.debug(f"RSS Bridge instance down: {instance}")

        await r.setex(
            "healthy_bridge_instances",
            cfg.redis.rsshub_health_ttl,
            json.dumps(healthy_bridge),
        )
        await r.aclose()

        # Alert admin if RSSHub is down
        if not rsshub_healthy:
            from bot.utils.logger import STFLogger
            from bot.models import LogModule
            log = STFLogger(LogModule.SYSTEM)
            await log.error(
                f"⚠️ RSSHub is DOWN at {cfg.rsshub.url} — "
                "Twitter/Instagram/TikTok/Threads/Facebook/Discord feeds will fail."
            )

        return {
            "rsshub": {"healthy": rsshub_healthy, "url": cfg.rsshub.url},
            "rssbridge": {
                "healthy": len(healthy_bridge),
                "total": len(cfg.platform.rssbridge_instances),
            },
        }

    return _run(_health())


# ─────────────────────────────────────────────
#  Task: Monitor Payment (CoinEx polling)
# ─────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="worker.tasks.monitor_payment_task",
    max_retries=240,
    default_retry_delay=90,
)
def monitor_payment_task(self, tx_id: int) -> dict:
    """Poll CoinEx every 90s for up to 6 hours until payment confirmed."""

    async def _monitor():
        from datetime import datetime, timezone
        from bot.database import init_db, get_session
        from bot.models import Transaction, TransactionStatus, User
        from bot.services.payment_service import check_deposit
        from sqlalchemy import select

        await init_db()
        async with get_session() as session:
            tx = (await session.execute(
                select(Transaction).where(Transaction.id == tx_id)
            )).scalar_one_or_none()

            if not tx:
                return {"skipped": True, "reason": "tx not found"}
            if tx.status == TransactionStatus.APPROVED:
                return {"skipped": True, "reason": "already activated"}
            if tx.status != TransactionStatus.PENDING:
                return {"skipped": True, "reason": f"status={tx.status}"}

            now = datetime.now(timezone.utc)
            if tx.address_expires_at and tx.address_expires_at < now:
                tx.status = TransactionStatus.REJECTED
                await session.commit()
                return {"expired": True}

            result = await check_deposit(
                tx.deposit_address,
                tx.network,
                float(tx.amount_usdt),
                tx.address_generated_at or tx.created_at,
            )

            if result and result.get("confirmed") and result.get("enough"):
                user = (await session.execute(
                    select(User).where(User.id == tx.user_id)
                )).scalar_one_or_none()

                if user:
                    from bot.utils.fixes import activate_subscription_safe
                    activated = await activate_subscription_safe(
                        tx_id=tx_id,
                        deposit_result=result,
                        reviewed_by="auto:coinex",
                    )
                    return {"activated": activated, "txid": result.get("txid")}

        return {"pending": True}

    try:
        return _run(_monitor())
    except Exception as exc:
        # v3.2: alert developer immediately on payment task crash
        import asyncio as _asyncio
        from bot.utils.alerts import alert_payment
        _asyncio.ensure_future(alert_payment(
            "Payment Monitor Crashed",
            f"monitor_payment_task failed for tx_id={tx_id}",
            exception=str(exc),
            tx_id=tx_id,
            action="Check logs; payment may need manual review",
        ))
        raise self.retry(exc=exc)



# ─────────────────────────────────────────────
#  Platform Error Rate Tracking (called from base.py)
# ─────────────────────────────────────────────

async def record_fetch_result(platform: str, success: bool) -> None:
    """
    Record fetch success/failure for platform error rate dashboard.
    PERF-4: Uses shared Redis pool from bot.cache instead of private client.
    """
    try:
        from bot.cache import get_redis
        from datetime import datetime, timezone

        r = await get_redis()
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y%m%d%H")
        day_key  = now.strftime("%Y%m%d")
        status   = "success" if success else "fail"
        pipe = r.pipeline()
        pipe.incr(f"fetch:{status}:{platform}:{hour_key}")
        pipe.expire(f"fetch:{status}:{platform}:{hour_key}", 172800)
        pipe.incr(f"fetch:{status}:{platform}:{day_key}")
        pipe.expire(f"fetch:{status}:{platform}:{day_key}", 172800)
        await pipe.execute()
    except Exception:
        pass  # Never let tracking break the fetch flow


# ─────────────────────────────────────────────
#  Webhook Success/Failure Tracking
# ─────────────────────────────────────────────

# Module-level sync Redis pool for webhook tracking (PERF-1 fix)
_webhook_redis_pool = None


def _get_webhook_redis():
    """Return a Redis client backed by a shared connection pool."""
    import redis as redis_lib
    from config import config as cfg
    global _webhook_redis_pool
    if _webhook_redis_pool is None:
        _webhook_redis_pool = redis_lib.ConnectionPool.from_url(
            cfg.redis.url, decode_responses=True
        )
    return redis_lib.Redis(connection_pool=_webhook_redis_pool)


def record_webhook_result(success: bool) -> None:
    """
    Record Telegram webhook success/failure.
    Called from bot middleware after every update is processed.
    Uses a shared connection pool — no new TCP connection per call.
    """
    try:
        from datetime import datetime, timezone

        r = _get_webhook_redis()
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y%m%d%H")
        day_key = now.strftime("%Y%m%d")

        status = "success" if success else "fail"
        pipe = r.pipeline()
        pipe.incr(f"webhook:{status}:{hour_key}")
        pipe.expire(f"webhook:{status}:{hour_key}", 172800)
        pipe.incr(f"webhook:{status}:{day_key}")
        pipe.expire(f"webhook:{status}:{day_key}", 172800)
        pipe.execute()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Task: Payment Retry Queue
#  Runs every 5 min via beat — rechecks PENDING crypto txs older than 10 min.
#  Guards against: CoinEx webhook miss, bot downtime, network blips.
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="worker.tasks.retry_pending_payments", bind=True, max_retries=3)
def retry_pending_payments(self):
    """Recheck PENDING crypto transactions that are >10 min old."""

    async def _run_retry():
        from bot.database import init_db, get_session
        from bot.models import Transaction, TransactionStatus, TransactionMethod
        from bot.services.payment_service import check_deposit
        from bot.utils.fixes import activate_subscription_safe
        from sqlalchemy import select
        from datetime import timedelta

        await init_db()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

        async with get_session() as session:
            txs = (await session.execute(
                select(Transaction).where(
                    Transaction.status == TransactionStatus.PENDING,
                    Transaction.payment_method == TransactionMethod.CRYPTO,
                    Transaction.deposit_address.isnot(None),
                    Transaction.created_at <= cutoff,
                )
            )).scalars().all()

        logger.info(f"[retry_pending_payments] Checking {len(txs)} stale PENDING transactions")

        for tx in txs:
            try:
                result = await check_deposit(
                    tx.deposit_address,
                    tx.network,
                    float(tx.amount_usdt),
                    tx.address_generated_at or tx.created_at,
                )
                if result and result.get("confirmed") and result.get("enough"):
                    activated = await activate_subscription_safe(
                        tx_id=tx.id,
                        deposit_result=result,
                        reviewed_by="auto:retry",
                    )
                    if activated:
                        logger.info(f"[retry_pending_payments] Activated tx={tx.id} via retry")
            except Exception as exc:
                logger.warning(f"[retry_pending_payments] tx={tx.id} check failed: {exc}")

    try:
        _run(_run_retry())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


# ─────────────────────────────────────────────────────────────────────────────
#  Task: Anomaly Alert System
#  Runs every 5 min via beat — checks for anomalies and notifies admin.
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="worker.tasks.check_anomalies_task")
def check_anomalies_task():
    """Check for system anomalies and push alerts to admin via Telegram."""
    async def _run_check():
        from bot.database import init_db
        from bot.handlers.admin_tg import check_anomalies_and_notify
        from telegram import Bot

        await init_db()
        bot = Bot(token=config.telegram.token)
        await check_anomalies_and_notify(bot)

    try:
        _run(_run_check())
    except Exception as e:
        logger.warning(f"[check_anomalies_task] Failed: {e}")
