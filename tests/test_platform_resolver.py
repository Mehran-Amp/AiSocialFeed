import pytest

from bot.services.platform_resolver import _extract_instagram_username

def test_extract_instagram_username_url():
    assert _extract_instagram_username("https://www.instagram.com/johndoe/") == "johndoe"
    assert _extract_instagram_username("http://instagram.com/johndoe") == "johndoe"
    assert _extract_instagram_username("instagram.com/john.doe_123") == "john.doe_123"
    assert _extract_instagram_username("https://instagram.com/johndoe?igshid=12345") == "johndoe"

def test_extract_instagram_username_handle():
    assert _extract_instagram_username("@johndoe") == "johndoe"
    assert _extract_instagram_username("johndoe") == "johndoe"
    assert _extract_instagram_username("@john.doe_123") == "john.doe_123"
    assert _extract_instagram_username("john.doe_123") == "john.doe_123"

def test_extract_instagram_username_invalid():
    assert _extract_instagram_username("https://twitter.com/johndoe") is None
    assert _extract_instagram_username("invalid!username") is None
    assert _extract_instagram_username("instagram.com/") is None
    assert _extract_instagram_username("https://instagram.com") is None
    assert _extract_instagram_username("@johndoe!") is None
