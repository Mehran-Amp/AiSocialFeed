"""
SocialtoFeed — Payment Service v3.2
CoinEx API integration for USDT crypto payments (TRC20 / BEP20 / ERC20).
Called from crypto_payment handler and Celery monitor task.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from config.settings import config

logger = logging.getLogger(__name__)

COINEX_BASE = "https://api.coinex.com/v2"
NETWORK_LABELS = {
    "TRC20": "TRC20 (TRON)",
    "BEP20": "BEP20 (BSC)",
    "ERC20": "ERC20 (ETH)",
}


def _coinex_headers(method: str, path: str, body_str: str = "") -> dict:
    """Generate signed CoinEx v2 API headers."""
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{method}\n{path}\n\n{body_str}\n{timestamp}"
    signature = hmac.new(
        config.payment.coinex_secret_key.encode("utf-8"),
        sign_str.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {
        "X-COINEX-KEY": config.payment.coinex_access_id,
        "X-COINEX-SIGN": signature,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }


async def get_deposit_address(user_id: int, network: str, amount: float) -> Optional[dict]:
    """
    Request a unique deposit address from CoinEx for the given network.
    Returns dict: address, network, network_label, amount, expires_at — or None on failure.
    """
    if not config.payment.is_configured:
        logger.error("CoinEx not configured — missing ACCESS_ID or SECRET_KEY")
        return None

    path = "/v2/assets/deposit-address"
    params = {"ccy": "USDT", "chain": network}
    body_str = json.dumps(params, separators=(",", ":"))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{COINEX_BASE}/assets/deposit-address",
                headers=_coinex_headers("POST", path, body_str),
                content=body_str,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"CoinEx address error: {data.get('message', data)}")
                return None

            address = data["data"]["address"]
            expires_at = datetime.now(timezone.utc) + timedelta(
                hours=config.payment.address_expiry_hours
            )
            return {
                "address": address,
                "network": network,
                "network_label": NETWORK_LABELS.get(network, network),
                "amount": amount,
                "expires_at": expires_at,
            }
    except Exception as e:
        logger.error(f"get_deposit_address error: {e}")
        return None


async def check_deposit(
    address: str,
    network: str,
    expected_amount: float,
    since: datetime,
) -> Optional[dict]:
    """
    Check CoinEx deposit history for a matching confirmed transaction.
    Returns dict: txid, amount, confirmations, confirmed, enough — or None if not found.
    """
    if not config.payment.is_configured:
        return None

    path = "/v2/assets/deposit-history"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{COINEX_BASE}/assets/deposit-history",
                headers=_coinex_headers("GET", path),
                params={"ccy": "USDT"},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"CoinEx deposit history error: {data.get('message', data)}")
                return None

            min_confirms = config.payment.confirm_blocks
            tolerance = 1 - config.payment.overpay_tolerance
            since_ts = since.timestamp() if since else 0.0

            for tx in data.get("data", {}).get("records", []):
                tx_address = tx.get("to_address", "")
                tx_chain = tx.get("chain", "")
                tx_amount = float(tx.get("amount", 0))
                tx_confirms = int(tx.get("confirmations", 0))

                # BUG-5 fix: skip deposits older than payment request creation time
                tx_time_ms = tx.get("created_at") or tx.get("actual_time_at") or 0
                tx_timestamp = int(tx_time_ms) / 1000 if tx_time_ms else 0.0
                if tx_timestamp and tx_timestamp < since_ts:
                    continue  # this deposit predates this payment request

                if (
                    tx_address.lower() == address.lower()
                    and tx_chain == network
                    and tx_amount >= expected_amount * tolerance
                ):
                    return {
                        "txid": tx.get("tx_id", ""),
                        "amount": tx_amount,
                        "confirmations": tx_confirms,
                        "confirmed": tx_confirms >= min_confirms,
                        "enough": tx_amount >= expected_amount * tolerance,
                        "txids": [tx.get("tx_id", "")],
                    }
        return None
    except Exception as e:
        logger.error(f"check_deposit error: {e}")
        return None


async def start_payment_monitor(tx_id: int) -> None:
    """
    Schedule a Celery task to poll CoinEx for payment confirmation.
    Retries every 90 seconds for up to 6 hours (240 retries).
    """
    try:
        from worker.tasks import celery_app
        celery_app.send_task(
            "worker.tasks.monitor_payment_task",
            args=[tx_id],
            countdown=config.payment.poll_interval,
        )
        logger.info(f"Payment monitor scheduled for tx_id={tx_id}")
    except Exception as e:
        logger.error(f"start_payment_monitor error: {e}")
