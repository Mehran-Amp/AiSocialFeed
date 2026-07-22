import pytest
from unittest.mock import patch, AsyncMock
from bot.utils.alerts import _set_rate_limit

@pytest.mark.asyncio
async def test_set_rate_limit_catches_exception():
    with patch("bot.cache.get_redis", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.side_effect = Exception("Redis connection failed")

        # Should not raise an exception
        await _set_rate_limit("test_alert")

        mock_get_redis.assert_called_once()
