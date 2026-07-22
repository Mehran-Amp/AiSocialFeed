import pytest
from bot.utils.telegram_utils import get_error_message, ERROR_MESSAGES

def test_get_error_message_known_key_no_formatting():
    """Test retrieving a message that doesn't need formatting."""
    message = get_error_message("private_account")
    assert message == ERROR_MESSAGES["private_account"]
    assert "باید پابلیک باشه" in message

def test_get_error_message_unknown_key_fallback():
    """Test that an unknown key falls back to the generic message."""
    message = get_error_message("some_random_unknown_key")
    assert message == ERROR_MESSAGES["generic"]
    assert "یه خطای موقت رخ داد" in message

def test_get_error_message_with_formatting():
    """Test that a message with format string works correctly."""
    message = get_error_message("platform_down", platform="YouTube")
    assert message == ERROR_MESSAGES["platform_down"].format(platform="YouTube")
    assert "سرویس YouTube فعلاً در دسترس نیست" in message

def test_get_error_message_missing_formatting_kwargs():
    """Test that missing kwargs for formatting return the unformatted template without crashing."""
    message = get_error_message("platform_down")
    assert message == ERROR_MESSAGES["platform_down"]
    assert "{platform}" in message
