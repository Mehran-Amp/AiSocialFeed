"""
SocialtoFeed — Shared Async Redis Pool  (PERF-4 fix)

Previously every module that needed Redis created its own connection:
  - worker/tasks.py          → _tracking_redis
  - bot/platforms/fetchers.py → _cookie_redis
  - bot/platforms/base.py    → _footer_redis
  - bot/services/ai_service.py → _redis_ai
  - bot/services/plan_service.py → _redis
  - worker/growth.py         → _upsell_redis

Six separate pools to the same Redis server is wasteful and makes
reconnect logic inconsistent (ai_service had no ping-reconnect at all).

This module provides a single shared pool via get_redis().
RedisPersistenceBackend keeps its own private connection — it manages
its own lifecycle and encoding, so it is intentionally excluded here.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_redis_pool: Optional["aioredis.Redis"] = None  # type: ignore[name-defined]


async def get_redis():
    """
    Return the shared async Redis client.
    Creates the pool on first call; reconnects automatically if the
    connection has dropped (ping-based health check).

    Usage:
        from bot.cache import get_redis
        r = await get_redis()
        await r.set("key", "value")
    """
    global _redis_pool
    import redis.asyncio as aioredis
    from config.settings import config

    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            config.redis.url,
            decode_responses=True,
            max_connections=20,
        )
        logger.debug("Shared Redis pool created.")

    try:
        await _redis_pool.ping()
    except Exception as e:
        logger.warning(f"Redis ping failed ({e}), reconnecting…")
        try:
            await _redis_pool.aclose()
        except Exception:
            pass
        _redis_pool = aioredis.from_url(
            config.redis.url,
            decode_responses=True,
            max_connections=20,
        )

    return _redis_pool


async def close_redis() -> None:
    """Gracefully close the shared pool on shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            logger.info("Shared Redis pool closed.")
        except Exception as e:
            logger.warning(f"Redis pool close error: {e}")
        finally:
            _redis_pool = None
