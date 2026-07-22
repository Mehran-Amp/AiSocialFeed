import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from telegram.error import TelegramError

from bot.utils.telegram_utils import safe_send_message


@pytest.mark.asyncio
async def test_safe_send_message_retry():
    # Setup the mocks
    mock_bot = AsyncMock()

    # We want send_message to fail on the first call, and succeed on the second call.
    mock_message = object()

    # Create the TelegramError object
    error = TelegramError("Test Error")

    mock_bot.send_message.side_effect = [error, mock_message]

    # Mock bot.utils.telegram_utils.get_bot
    with patch("bot.utils.telegram_utils.get_bot", return_value=mock_bot):
        # Mock asyncio.sleep so we don't actually wait
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            # Execute the function we are testing
            result = await safe_send_message(
                chat_id=12345,
                text="Test Message"
            )

            # Assertions
            assert result is mock_message

            # send_message should have been called twice (1 failure, 1 success)
            assert mock_bot.send_message.call_count == 2

            # Sleep should have been called once, after the first failure
            mock_sleep.assert_called_once_with(1.0) # 1.5 ** 0 == 1.0
