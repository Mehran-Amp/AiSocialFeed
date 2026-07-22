"""
SocialtoFeed — Alert Dispatcher v3.2

Two-channel routing:
  CRITICAL  → ADMIN_TELEGRAM_ID  (personal, immediate, always delivered)
  OPERATIONAL/WARNING → ADMIN_CHANNEL_ID  (channel, rate-limited, searchable)

Rate limiting: same alert_type suppressed for config.admin.alert_rate_limit_seconds
via Redis key  alert:rl:{alert_type}

Usage:
    from bot.utils.alerts import alert_critical, alert_warning, alert_operational, alert_error

    await alert_critical("Circuit Breaker", "twitter opened after 5 failures",
                         platform="twitter", action="Fetches paused 30 min")

    await alert_warning("High Error Rate", "Reddit at 40% fail rate",
                        platform="reddit")

    await alert_operational("New User", "faridamp joined via referral",
                            user_id=123456)

    await alert_error("fetch_account_task", exc, user_id=42, account_id=99)
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import config

logger = logging.getLogger(__name__)

# ── Severity icons ──────────────────────────────────────────────────────────
_ICONS = {
    "CRITICAL":    "🚨",
    "WARNING":     "⚠️",
    "INFO":        "ℹ️",
    "ERROR":       "❌",
    "PAYMENT":     "💳",
    "USER":        "👤",
    "PLATFORM":    "🔌",
    "SYSTEM":      "🖥",
    "SECURITY":    "🔒",
}


# ── Rate limit helpers (Redis-backed) ───────────────────────────────────────

async def _is_rate_limited(alert_type: str) -> bool:
    """Return True when this alert_type was sent within the rate-limit window."""
    try:
        from bot.cache import get_redis
        r = await get_redis()
        key = f"alert:rl:{alert_type}"
        return bool(await r.exists(key))
    except Exception:
        return False  # fail-open: never suppress on Redis error


async def _set_rate_limit(alert_type: str) -> None:
    try:
        from bot.cache import get_redis
        r = await get_redis()
        key = f"alert:rl:{alert_type}"
        await r.set(key, "1", ex=config.admin.alert_rate_limit_seconds)
    except Exception:
        pass


# ── Message builder ─────────────────────────────────────────────────────────

def _build_message(
    severity: str,
    title: str,
    body: str,
    **ctx: Any,
) -> str:
    icon  = _ICONS.get(severity, "🔔")
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"{icon} <b>{severity} — {title}</b>", "━━━━━━━━━━━━━━━━━━━━"]
    if body:
        lines.append(body)
    if ctx:
        lines.append("")
        for k, v in ctx.items():
            if v is not None:
                label = k.replace("_", " ").title()
                lines.append(f"<b>{label}:</b> <code>{v}</code>")
    lines.append(f"\n🕐 {now}")
    return "\n".join(lines)


# ── Send helpers ─────────────────────────────────────────────────────────────

async def _send_to_personal(text: str) -> None:
    """Always send — no rate limiting. Personal admin ID."""
    from bot.utils.telegram_utils import send_admin_alert
    await send_admin_alert(text)


async def _send_to_channel(text: str) -> None:
    """Send to admin channel. Silently skips if channel not configured."""
    if not config.admin.channel_configured:
        logger.debug("ADMIN_CHANNEL_ID not set — operational alert skipped")
        return
    try:
        from bot.utils.telegram_utils import get_bot
        from telegram.constants import ParseMode
        bot = get_bot()
        await bot.send_message(
            chat_id=config.admin.admin_channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"[alerts] channel send failed: {e}")


# ── Public API ───────────────────────────────────────────────────────────────

async def alert_critical(title: str, body: str = "", **ctx: Any) -> None:
    """
    CRITICAL: immediate, personal, never rate-limited.
    Use for: circuit breaker open, payment crash, worker down, webhook silent.
    """
    text = _build_message("CRITICAL", title, body, **ctx)
    await _send_to_personal(text)
    logger.critical(f"[ALERT] {title} — {body}")


async def alert_warning(
    title: str, body: str = "", alert_type: Optional[str] = None, **ctx: Any
) -> None:
    """
    WARNING: personal ID, rate-limited per alert_type.
    Use for: error rate rising, subscription approaching expiry batch.
    """
    key = alert_type or title.lower().replace(" ", "_")
    if await _is_rate_limited(key):
        logger.debug(f"[alerts] warning '{title}' suppressed by rate limit")
        return
    text = _build_message("WARNING", title, body, **ctx)
    await _send_to_personal(text)
    await _set_rate_limit(key)
    logger.warning(f"[ALERT] {title} — {body}")


async def alert_operational(
    title: str, body: str = "", alert_type: Optional[str] = None, **ctx: Any
) -> None:
    """
    INFO: admin channel, rate-limited.
    Use for: new user joined, daily backup, digest-level events.
    """
    key = alert_type or title.lower().replace(" ", "_")
    if await _is_rate_limited(key):
        return
    text = _build_message("INFO", title, body, **ctx)
    await _send_to_channel(text)
    await _set_rate_limit(key)


async def alert_error(
    context_name: str,
    exc: Exception,
    alert_type: Optional[str] = None,
    **ctx: Any,
) -> None:
    """
    ERROR: structured exception alert → personal ID, rate-limited.
    Includes file, line, traceback summary.
    Use for: task crash, handler exception, DB error.
    """
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_short = "".join(tb_lines[-6:]).strip()[:600]  # last 6 lines, max 600 chars

    key = alert_type or f"error_{context_name}_{type(exc).__name__}"
    if await _is_rate_limited(key):
        return

    text = _build_message(
        "ERROR",
        f"Exception in {context_name}",
        f"<code>{tb_short}</code>",
        exception_type=type(exc).__name__,
        **ctx,
    )
    await _send_to_personal(text)
    await _set_rate_limit(key)
    logger.error(f"[ALERT] exception in {context_name}: {exc}")


async def alert_payment(title: str, body: str = "", **ctx: Any) -> None:
    """Payment-specific alert — always personal, never rate-limited."""
    text = _build_message("PAYMENT", title, body, **ctx)
    await _send_to_personal(text)
    logger.critical(f"[PAYMENT ALERT] {title} — {body}")
