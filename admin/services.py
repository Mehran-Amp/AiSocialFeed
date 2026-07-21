"""
SocialtoFeed — Admin Services
Business logic for admin actions: approve subscription, Tronscan verify.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def activate_subscription(tx, reviewed_by: str = "admin") -> None:
    """
    Approve a transaction and activate user subscription.
    Sends Telegram notification to user.
    Called from Django admin action.
    """
    from .django_models import TransactionProxy, UserProxy, PlanConfigProxy
    from django.utils import timezone as dj_tz

    if tx.status != "pending":
        raise ValueError(f"Transaction {tx.id} is not pending (status: {tx.status})")

    # Get plan config for duration
    plan_name = tx.plan
    period = tx.period

    duration_days = {"monthly": 30, "biannual": 183, "yearly": 365}.get(period, 30)

    # Update transaction
    tx.status = "approved"
    tx.reviewed_at = datetime.now(timezone.utc)
    tx.reviewed_by = reviewed_by
    tx.save(update_fields=["status", "reviewed_at", "reviewed_by"])

    # Update user plan
    user = UserProxy.objects.get(pk=tx.user_id)
    now = datetime.now(timezone.utc)

    # If user already has active subscription, extend it
    if user.subscription_expires_at and user.subscription_expires_at > now:
        new_expiry = user.subscription_expires_at + timedelta(days=duration_days)
    else:
        new_expiry = now + timedelta(days=duration_days)

    user.plan = plan_name
    user.subscription_expires_at = new_expiry
    user.subscription_pause_used = False  # Reset pause on renewal
    user.save(update_fields=["plan", "subscription_expires_at", "subscription_pause_used"])

    # Notify user via Telegram (async)
    _notify_user_approved(user.telegram_id, plan_name, new_expiry, user.language)

    logger.info(
        f"Subscription activated: user={user.telegram_id} "
        f"plan={plan_name} expires={new_expiry.date()}"
    )


def reject_transaction(tx, reason: str, reviewed_by: str = "admin") -> None:
    """Reject a transaction and notify user."""
    from .django_models import UserProxy

    tx.status = "rejected"
    tx.reviewed_at = datetime.now(timezone.utc)
    tx.reviewed_by = reviewed_by
    tx.reject_reason = reason
    tx.save(update_fields=["status", "reviewed_at", "reviewed_by", "reject_reason"])

    user = UserProxy.objects.get(pk=tx.user_id)
    _notify_user_rejected(user.telegram_id, reason, user.language)


def _notify_user_approved(telegram_id: int, plan: str, expires: datetime, lang: str) -> None:
    """Sync wrapper — for Django admin (sync) context only. async callers use await directly."""
    _run_async(_notify_user_approved_async(telegram_id, plan, expires, lang))


async def _notify_user_approved_async(telegram_id: int, plan: str, expires: datetime, lang: str) -> None:
    """Async notification — awaited from bot/utils/fixes.py:activate_subscription_safe."""
    from bot.utils.telegram_utils import safe_send_message
    from bot.utils.translator import t
    msg = t(
        "subscription.approved", lang,
        plan=plan.capitalize(),
        expires=expires.strftime("%Y-%m-%d"),
    )
    await safe_send_message(telegram_id, msg, parse_mode="HTML")


def _notify_user_rejected(telegram_id: int, reason: str, lang: str) -> None:
    async def _send():
        from bot.utils.telegram_utils import safe_send_message
        from bot.utils.translator import t
        msg = t("subscription.rejected", lang, reason=reason or "No reason provided")
        await safe_send_message(telegram_id, msg, parse_mode="HTML")

    _run_async(_send())


def send_broadcast(message: str, plan_filter: str = "all") -> int:
    """
    Send a broadcast message to users.
    plan_filter: "all", "pro", "premium"
    Returns number of messages sent.
    """
    from .django_models import UserProxy
    from bot.utils.telegram_utils import safe_send_message

    if plan_filter == "all":
        users = UserProxy.objects.filter(is_banned=False).values_list("telegram_id", "language")
    else:
        users = UserProxy.objects.filter(
            plan=plan_filter, is_banned=False
        ).values_list("telegram_id", "language")

    async def _broadcast():
        import asyncio
        sent = 0
        for telegram_id, _ in users:
            try:
                await safe_send_message(telegram_id, message, parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)  # 20/sec — stay under Telegram limits
            except Exception as e:
                logger.warning(f"Broadcast failed for {telegram_id}: {e}")
        return sent

    return _run_async(_broadcast())


async def verify_txid_tronscan(txid: str, expected_amount: float, expected_address: str) -> dict:
    """
    Verify a USDT TRC20 transaction via Tronscan API.
    Returns dict with: valid (bool), amount, from_address, to_address, timestamp
    """
    import httpx
    from config import config

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{config.payment.tronscan_api_url}/transaction-info",
                params={"hash": txid},
            )
            if resp.status_code != 200:
                return {"valid": False, "error": f"HTTP {resp.status_code}"}

            data = resp.json()

            # Extract transfer info
            contracts = data.get("contractData", {})
            to_address = contracts.get("to_address", "")
            amount_raw = contracts.get("amount", 0)
            amount = float(amount_raw) / 1_000_000  # USDT has 6 decimals

            from_address = data.get("ownerAddress", "")
            timestamp = data.get("timestamp", 0)
            confirmed = data.get("confirmed", False)

            # Validate
            tx_age_hours = (
                (datetime.now(timezone.utc).timestamp() * 1000 - timestamp) / 3600000
            )

            valid = (
                confirmed and
                to_address.lower() == expected_address.lower() and
                abs(amount - expected_amount) / expected_amount <= 0.05 and
                tx_age_hours <= 48
            )

            return {
                "valid": valid,
                "amount": amount,
                "from_address": from_address,
                "to_address": to_address,
                "confirmed": confirmed,
                "age_hours": round(tx_age_hours, 1),
                "expected_amount": expected_amount,
                "amount_match": abs(amount - expected_amount) / max(expected_amount, 0.01) <= 0.05,
            }

    except Exception as e:
        logger.error(f"Tronscan verification failed: {e}")
        return {"valid": False, "error": str(e)}


def _run_async(coro) -> any:
    """Run async coroutine from sync Django context using asyncio.run()."""
    try:
        return asyncio.run(coro)
    except Exception as e:
        logger.error(f"Async execution failed: {e}")
        return None
