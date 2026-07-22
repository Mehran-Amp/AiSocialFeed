"""
SocialtoFeed — Structured Logger
Logs to: console + rotating file + database + Telegram alerts for critical errors.
v3.2: Correlation ID per Telegram update for per-session tracing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import config
from bot.models import LogLevel, LogModule, Platform, SystemLog

logger = logging.getLogger(__name__)

# Track last alert time per error type to prevent spam
_last_alert: dict[str, datetime] = {}

# ─────────────────────────────────────────────
#  Correlation ID — per-update request tracing
# ─────────────────────────────────────────────

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(rid: str) -> None:
    """Set correlation ID for this async context (called in auth middleware)."""
    _request_id_var.set(rid)


def get_request_id() -> str:
    """Get correlation ID for current async context."""
    return _request_id_var.get()


class CorrelationIdFilter(logging.Filter):
    """Injects request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


# ─────────────────────────────────────────────
#  Setup standard Python logging
# ─────────────────────────────────────────────

def setup_logging() -> None:
    """
    Configure root logger with:
    - Console handler (INFO+)
    - Rotating file handler (DEBUG+)
    """
    import os
    os.makedirs(config.logging.log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # v3.2: include request_id in every log line for per-session tracing
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(request_id)-12s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    corr_filter = CorrelationIdFilter()

    # Console
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, config.logging.level, logging.INFO))
    console.setFormatter(fmt)
    console.addFilter(corr_filter)
    root.addHandler(console)

    # Rotating file — respects LOG_LEVEL; never logs below INFO to avoid
    # storing full Telegram update JSON (user IDs, message text) on disk.
    file_log_level = max(
        getattr(logging, config.logging.level, logging.INFO),
        logging.INFO,  # floor at INFO — never write DEBUG payloads to disk
    )
    file_handler = logging.handlers.RotatingFileHandler(
        config.logging.log_file,
        maxBytes=config.logging.max_bytes,
        backupCount=config.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(file_log_level)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(corr_filter)
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger.info("Logging initialized.")


# ─────────────────────────────────────────────
#  STFLogger — structured logging class
# ─────────────────────────────────────────────

class STFLogger:
    """
    Structured logger for SocialtoFeed.
    Writes to DB and optionally alerts admin via Telegram.

    Usage:
        log = STFLogger(LogModule.YOUTUBE)
        await log.error("Channel fetch failed", account_id=42, details={"url": "..."})
    """

    def __init__(self, module: LogModule):
        self.module = module
        self._py_logger = logging.getLogger(f"stf.{module.value}")

    async def _write(
        self,
        level: LogLevel,
        message: str,
        user_id: Optional[int] = None,
        account_id: Optional[int] = None,
        platform: Optional[Platform] = None,
        details: Optional[dict] = None,
        extra: Optional[dict] = None,
        exc: Optional[Exception] = None,
    ) -> None:
        # Build details dict
        details_data = details or {}
        if exc:
            details_data["exception"] = type(exc).__name__
            details_data["traceback"] = traceback.format_exc()

        # Python logger
        py_level = getattr(logging, level.value, logging.INFO)
        log_msg = f"{message}"
        if user_id:
            log_msg += f" [user:{user_id}]"
        if account_id:
            log_msg += f" [account:{account_id}]"
        self._py_logger.log(py_level, log_msg, exc_info=exc is not None)

        # DB log (fire and forget — don't let logging failures crash the app)
        try:
            await self._save_to_db(
                level=level,
                message=message,
                user_id=user_id,
                account_id=account_id,
                platform=platform,
                details=details_data if details_data else None,
                extra=extra,
            )
        except Exception as db_err:
            self._py_logger.warning(f"Failed to save log to DB: {db_err}")

        # Telegram alert for serious issues
        if level in (LogLevel.ERROR, LogLevel.CRITICAL):
            await self._maybe_alert_admin(level, message, details_data, account_id, platform)

    async def _save_to_db(self, **kwargs) -> None:
        from bot.database import get_session
        async with get_session() as session:
            entry = SystemLog(module=self.module, **kwargs)
            session.add(entry)

    async def _maybe_alert_admin(
        self,
        level: LogLevel,
        message: str,
        details: dict,
        account_id: Optional[int],
        platform: Optional[Platform],
    ) -> None:
        """Send Telegram alert to admin, with cooldown to prevent spam."""
        alert_key = f"{self.module.value}:{message[:50]}"
        now = datetime.now(timezone.utc)
        last = _last_alert.get(alert_key)

        if last:
            elapsed = (now - last).total_seconds()
            if elapsed < config.logging.alert_cooldown_seconds:
                return  # cooldown not expired

        _last_alert[alert_key] = now

        # Build alert message
        tb = details.get("traceback", "")
        tb_short = "\n".join(tb.splitlines()[-6:]) if tb else ""  # last 6 lines

        text = (
            f"{'🚨' if level == LogLevel.CRITICAL else '⚠️'} "
            f"<b>SocialtoFeed {level.value}</b>\n\n"
            f"<b>Module:</b> {self.module.value}\n"
            f"<b>Message:</b> {message}\n"
        )
        if platform:
            text += f"<b>Platform:</b> {platform.value}\n"
        if account_id:
            text += f"<b>Account ID:</b> {account_id}\n"
        if tb_short:
            text += f"\n<pre>{tb_short}</pre>"

        # Send via Telegram (import here to avoid circular deps)
        try:
            from bot.utils.telegram_utils import send_admin_alert
            await send_admin_alert(text)
        except Exception as e:
            self._py_logger.warning(f"Failed to send Telegram alert: {e}")

    # ── Public interface ──────────────────────

    async def debug(self, message: str, **kwargs) -> None:
        await self._write(LogLevel.DEBUG, message, **kwargs)

    async def info(self, message: str, **kwargs) -> None:
        await self._write(LogLevel.INFO, message, **kwargs)

    async def warning(self, message: str, **kwargs) -> None:
        await self._write(LogLevel.WARNING, message, **kwargs)

    async def error(self, message: str, exc: Optional[Exception] = None, **kwargs) -> None:
        await self._write(LogLevel.ERROR, message, exc=exc, **kwargs)

    async def critical(self, message: str, exc: Optional[Exception] = None, **kwargs) -> None:
        await self._write(LogLevel.CRITICAL, message, exc=exc, **kwargs)


# ─────────────────────────────────────────────
#  Debug Report Generator
# ─────────────────────────────────────────────

async def generate_debug_report() -> dict:
    """
    Generates a full system debug report.
    Called from admin panel — output can be sent to developer.
    """
    import platform as sys_platform
    import psutil
    import sys

    from bot.database import get_session, check_db_connection
    import redis.asyncio as aioredis

    report: dict[str, Any] = {
        "report_id": f"DBG-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # System info
    try:
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        disk = psutil.disk_usage("/")
        report["system"] = {
            "python_version": sys.version,
            "os": f"{sys_platform.system()} {sys_platform.release()}",
            "memory_used_mb": round(mem.used / 1024 / 1024),
            "memory_total_mb": round(mem.total / 1024 / 1024),
            "memory_pct": mem.percent,
            "cpu_pct": cpu,
            "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
        }
    except Exception as e:
        report["system"] = {"error": str(e)}

    # Database
    try:
        db_ok = await check_db_connection()
        async with get_session() as session:
            from sqlalchemy import text, func, select
            from bot.models import User, Account, SentPost, Transaction, TransactionStatus

            total_users = (await session.execute(
                select(func.count()).select_from(User)
            )).scalar()
            active_subs = (await session.execute(
                select(func.count()).select_from(User).where(
                    User.plan.in_(["pro", "premium"])
                )
            )).scalar()
            total_accounts = (await session.execute(
                select(func.count()).select_from(Account)
            )).scalar()
            pending_tx = (await session.execute(
                select(func.count()).select_from(Transaction).where(
                    Transaction.status == TransactionStatus.PENDING
                )
            )).scalar()

        report["database"] = {
            "status": "ok" if db_ok else "error",
            "total_users": total_users,
            "active_subscriptions": active_subs,
            "total_accounts": total_accounts,
            "pending_transactions": pending_tx,
        }
    except Exception as e:
        report["database"] = {"status": "error", "error": str(e)}

    # Redis
    try:
        from bot.cache import get_redis  # PERF-4: shared pool
        r = await get_redis()
        await r.ping()
        info = await r.info("memory")
        report["redis"] = {
            "status": "ok",
            "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 1),
        }
    except Exception as e:
        report["redis"] = {"status": "error", "error": str(e)}

    # DeepSeek
    report["deepseek"] = {
        "api_key_set": bool(config.deepseek.api_key),
        "model_fast": config.deepseek.model_fast,
        "model_pro": config.deepseek.model_pro,
    }
    if config.deepseek.is_configured:
        try:
            # Quick connectivity test
            from bot.services.ai_service import AIService
            status = await AIService.health_check()
            report["deepseek"]["status"] = "ok" if status else "error"
        except Exception as e:
            report["deepseek"]["status"] = f"error: {e}"

    # Recent errors (last 20)
    try:
        async with get_session() as session:
            from sqlalchemy import select, desc
            recent_errors = (await session.execute(
                select(SystemLog)
                .where(SystemLog.level.in_([LogLevel.ERROR, LogLevel.CRITICAL]))
                .order_by(desc(SystemLog.created_at))
                .limit(20)
            )).scalars().all()

        report["recent_errors"] = [e.to_debug_dict() for e in recent_errors]
    except Exception as e:
        report["recent_errors"] = [{"error": str(e)}]

    # Config summary (no secrets)
    report["config"] = {
        "default_language": config.app.default_language,
        "webhook_mode": bool(config.telegram.webhook_url),
        "max_concurrent_downloads": config.download.max_concurrent,
        "dedup_window_days": config.app.dedup_window_days,
        "rsshub_url": config.rsshub.url,
        "rssbridge_instances_count": len(config.platform.rssbridge_instances),
        "nowpayments_enabled": config.payment.nowpayments_enabled,
    }

    return report
