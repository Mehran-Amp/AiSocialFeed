import pytest
from unittest.mock import AsyncMock, patch
from bot.utils.alerts import _is_rate_limited

@pytest.mark.asyncio
async def test_is_rate_limited_true():
    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 1

    with patch("bot.cache.get_redis", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis

        result = await _is_rate_limited("test_alert")

        assert result is True
        mock_redis.exists.assert_called_once_with("alert:rl:test_alert")

@pytest.mark.asyncio
async def test_is_rate_limited_false():
    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 0

    with patch("bot.cache.get_redis", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis

        result = await _is_rate_limited("test_alert")

        assert result is False
        mock_redis.exists.assert_called_once_with("alert:rl:test_alert")

@pytest.mark.asyncio
async def test_is_rate_limited_exception_get_redis():
    with patch("bot.cache.get_redis", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.side_effect = Exception("Redis connection failed")

        result = await _is_rate_limited("test_alert")

        assert result is False

@pytest.mark.asyncio
async def test_is_rate_limited_exception_exists():
    mock_redis = AsyncMock()
    mock_redis.exists.side_effect = Exception("Redis command failed")

    with patch("bot.cache.get_redis", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis

        result = await _is_rate_limited("test_alert")

        assert result is False
