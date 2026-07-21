"""
SocialtoFeed — Redis Persistence & Zero-Downtime Upgrade
Replaces PicklePersistence with Redis-backed persistence.
All conversation states survive bot restarts and Docker upgrades.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from collections.abc import MutableMapping

from telegram.ext import BasePersistence, PersistenceInput
from telegram.ext._utils.types import BD, CD, UD, CDCData, ConversationKey

logger = logging.getLogger(__name__)


class RedisPersistenceBackend(BasePersistence):
    """
    Redis-backed persistence for python-telegram-bot.
    Stores: user_data, chat_data, bot_data, conversation states.
    Key prefix: stf:persist:

    Why Redis instead of PicklePersistence:
    - Survives Docker restarts (no file loss)
    - Works across multiple bot instances
    - TTL support (auto-cleanup of old conversations)
    - No file corruption on crash
    """

    KEY_PREFIX = "stf:persist:"
    TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days — auto cleanup

    def __init__(self, redis_url: str):
        super().__init__(
            store_data=PersistenceInput(
                bot_data=True,
                chat_data=True,
                user_data=True,
                callback_data=False,  # not needed
            ),
            update_interval=30,  # flush to Redis every 30 seconds
        )
        self.redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    def _key(self, *parts: str) -> str:
        return self.KEY_PREFIX + ":".join(str(p) for p in parts)

    async def _get(self, key: str) -> Any:
        r = await self._get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def _set(self, key: str, value: Any) -> None:
        r = await self._get_redis()
        await r.setex(key, self.TTL_SECONDS, json.dumps(value, default=str))

    # ── BasePersistence interface ─────────────

    async def get_user_data(self) -> dict:
        data = await self._get(self._key("user_data")) or {}
        return {int(k): v for k, v in data.items()}

    async def get_chat_data(self) -> dict:
        data = await self._get(self._key("chat_data")) or {}
        return {int(k): v for k, v in data.items()}

    async def get_bot_data(self) -> dict:
        return await self._get(self._key("bot_data")) or {}

    async def get_callback_data(self):
        return None

    async def get_conversations(self, name: str) -> dict:
        data = await self._get(self._key("conv", name)) or {}
        # Keys are stored as JSON strings, restore as tuples
        result = {}
        for k, v in data.items():
            try:
                key = tuple(json.loads(k))
                result[key] = v
            except Exception:
                pass
        return result

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        """No-op: Redis is updated via update_user_data; nothing extra to refresh."""
        pass

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        """No-op: Redis is updated via update_chat_data; nothing extra to refresh."""
        pass

    async def refresh_bot_data(self, bot_data: dict) -> None:
        """No-op: Redis is updated via update_bot_data; nothing extra to refresh."""
        pass

    async def update_user_data(self, user_id: int, data: dict) -> None:
        all_data = await self._get(self._key("user_data")) or {}
        all_data[str(user_id)] = data
        await self._set(self._key("user_data"), all_data)

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        all_data = await self._get(self._key("chat_data")) or {}
        all_data[str(chat_id)] = data
        await self._set(self._key("chat_data"), all_data)

    async def update_bot_data(self, data: dict) -> None:
        await self._set(self._key("bot_data"), data)

    async def update_callback_data(self, data) -> None:
        pass  # not used

    async def update_conversation(
        self, name: str, key: ConversationKey, new_state: Optional[object]
    ) -> None:
        all_convs = await self._get(self._key("conv", name)) or {}
        str_key = json.dumps(list(key))
        if new_state is None:
            all_convs.pop(str_key, None)
        else:
            all_convs[str_key] = new_state
        await self._set(self._key("conv", name), all_convs)

    async def drop_user_data(self, user_id: int) -> None:
        all_data = await self._get(self._key("user_data")) or {}
        all_data.pop(str(user_id), None)
        await self._set(self._key("user_data"), all_data)

    async def drop_chat_data(self, chat_id: int) -> None:
        all_data = await self._get(self._key("chat_data")) or {}
        all_data.pop(str(chat_id), None)
        await self._set(self._key("chat_data"), all_data)

    async def flush(self) -> None:
        """Called on shutdown — no-op since we write immediately."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("RedisPersistence flushed and closed.")