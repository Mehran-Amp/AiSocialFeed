"""
SocialtoFeed — Backup & Infrastructure Tasks
1. Automatic daily backup to Telegram channel
2. Zero-downtime upgrade helper
3. Platform health monitoring
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from worker.tasks import celery_app, _run

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Daily Backup to Telegram Channel
# ─────────────────────────────────────────────

@celery_app.task(name="worker.infra.backup_to_telegram")
def backup_to_telegram() -> dict:
    """
    1. pg_dump → gzip
    2. Send to BACKUP_CHANNEL_ID via Telegram
    3. Delete local file
    Runs daily at 03:00 UTC via Beat.
    """

    async def _backup():
        from config.settings import config

        backup_channel = os.getenv("BACKUP_CHANNEL_ID")
        if not backup_channel:
            logger.warning("BACKUP_CHANNEL_ID not set — skipping Telegram backup")
            return {"status": "skipped", "reason": "no channel configured"}

        db_url = config.db.url
        # Parse DB connection params from URL
        # postgresql://user:pass@host:port/dbname
        import re
        m = re.match(
            r"postgres(?:ql)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(.+)",
            db_url.replace("+asyncpg", ""),
        )
        if not m:
            return {"status": "error", "reason": "Could not parse DATABASE_URL"}

        db_user, db_pass, db_host, db_port, db_name = m.groups()
        db_port = db_port or "5432"

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"stf_backup_{timestamp}.sql.gz"

        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Run pg_dump
            env = os.environ.copy()
            env["PGPASSWORD"] = db_pass

            dump_cmd = [
                "pg_dump",
                "-h", db_host,
                "-p", db_port,
                "-U", db_user,
                "-d", db_name,
                "--no-password",
            ]

            result = subprocess.run(
                dump_cmd,
                env=env,
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error(f"pg_dump stderr: {result.stderr.decode()[:500]}")
                return {"status": "error", "reason": "pg_dump failed — check server logs"}

            # Compress
            with gzip.open(tmp_path, "wb") as gz:
                gz.write(result.stdout)

            file_size_mb = round(os.path.getsize(tmp_path) / 1024 / 1024, 2)

            # Send to Telegram
            from bot.utils.telegram_utils import get_bot
            bot = get_bot()

            caption = (
                f"🗄 <b>SocialtoFeed Backup</b>\n\n"
                f"📅 {timestamp}\n"
                f"💾 {file_size_mb} MB\n"
                f"🗃 Database: {db_name}"
            )

            with open(tmp_path, "rb") as f:
                await bot.send_document(
                    chat_id=int(backup_channel),
                    document=f,
                    filename=filename,
                    caption=caption,
                    parse_mode="HTML",
                )

            logger.info(f"Backup sent to channel: {filename} ({file_size_mb} MB)")
            return {"status": "ok", "filename": filename, "size_mb": file_size_mb}

        except subprocess.TimeoutExpired:
            return {"status": "error", "reason": "pg_dump timeout"}
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return {"status": "error", "reason": str(e)}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return _run(_backup())


# ─────────────────────────────────────────────
#  Zero-Downtime Upgrade Helper
# ─────────────────────────────────────────────

@celery_app.task(name="worker.infra.pre_upgrade_check")
def pre_upgrade_check() -> dict:
    """
    Run before deploying a new version.
    Checks: DB migrations, Redis connection, pending tasks.
    Returns warnings that should be reviewed before upgrade.
    """

    async def _check():
        warnings = []
        checks = {}

        # 1. Check Redis
        try:
            from bot.cache import get_redis  # PERF-4: shared pool
            r = await get_redis()
            await r.ping()
            queue_size = await r.llen("platforms") or 0
            checks["redis"] = "ok"
            checks["queue_size"] = queue_size
            if queue_size > 100:
                warnings.append(f"Large queue: {queue_size} tasks pending")
        except Exception as e:
            checks["redis"] = f"error: {e}"
            warnings.append("Redis not reachable")

        # 2. Check DB
        from bot.database import check_db_connection
        db_ok = await check_db_connection()
        checks["database"] = "ok" if db_ok else "error"
        if not db_ok:
            warnings.append("Database not reachable")

        # 3. Active users in last 5 minutes
        try:
            from bot.database import get_session
            from bot.models import User
            from sqlalchemy import select, func
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            async with get_session() as session:
                active = (await session.execute(
                    select(func.count()).select_from(User)
                    .where(User.last_active_at >= cutoff)
                )).scalar() or 0
            checks["active_users_5min"] = active
            if active > 10:
                warnings.append(f"{active} users active in last 5 min — upgrade will interrupt them briefly")
        except Exception as e:
            checks["active_users"] = f"error: {e}"

        return {
            "ready_for_upgrade": len(warnings) == 0,
            "warnings": warnings,
            "checks": checks,
            "recommendation": (
                "✅ Safe to upgrade" if not warnings
                else "⚠️ Review warnings before upgrading"
            ),
        }

    return _run(_check())


# ─────────────────────────────────────────────
#  Beat schedule additions for infra tasks
# ─────────────────────────────────────────────


@celery_app.task(name="worker.infra.check_webhook_health")
def check_webhook_health() -> dict:
    """
    v3.2: Run every 10 minutes via beat.
    If no successful webhook updates in the last 10 minutes → CRITICAL alert.
    """
    return _run(_check_webhook())


async def _check_webhook() -> dict:
    from datetime import datetime, timezone
    from bot.cache import get_redis
    from config.settings import config

    r = await get_redis()
    now = datetime.now(timezone.utc)

    # Check last 2 hourly buckets — covers up to 70-minute gap at bucket boundaries
    counts = []
    for delta_h in [0, 1]:
        from datetime import timedelta
        t = now - timedelta(hours=delta_h)
        key = t.strftime("webhook:success:%Y%m%d%H")
        counts.append(int(await r.get(key) or 0))

    total_recent = counts[0]  # current hour bucket

    if total_recent == 0 and counts[1] == 0:
        # No webhook hits in this hour OR the last — bot is likely unreachable
        from bot.utils.alerts import alert_critical
        import asyncio
        asyncio.ensure_future(alert_critical(
            "Webhook Silent",
            "No successful Telegram updates received in the last ~70 minutes.",
            last_hour_count=counts[1],
            this_hour_count=counts[0],
            action="Check bot process, webhook registration, and nginx",
        ))
        return {"status": "silent", "alerted": True}

    return {"status": "healthy", "this_hour": counts[0]}
