import pytest
from bot.services.platform_resolver import _extract_twitter_username

def test_extract_twitter_username():
    # Test twitter.com URL format
    assert _extract_twitter_username("twitter.com/johndoe") == "johndoe"
    assert _extract_twitter_username("https://twitter.com/johndoe") == "johndoe"
    assert _extract_twitter_username("http://twitter.com/johndoe") == "johndoe"

    # Test x.com URL format
    assert _extract_twitter_username("x.com/johndoe") == "johndoe"
    assert _extract_twitter_username("https://x.com/johndoe") == "johndoe"
    assert _extract_twitter_username("http://x.com/johndoe") == "johndoe"

    # Test @ format
    assert _extract_twitter_username("@johndoe") == "johndoe"
    assert _extract_twitter_username("@john_doe123") == "john_doe123"

    # Test plain username format
    assert _extract_twitter_username("johndoe") == "johndoe"
    assert _extract_twitter_username("john_doe123") == "john_doe123"

    # Test ignored internal handles
    assert _extract_twitter_username("twitter.com/home") is None
    assert _extract_twitter_username("x.com/explore") is None
    assert _extract_twitter_username("@notifications") is None
    assert _extract_twitter_username("messages") is None
    assert _extract_twitter_username("twitter.com/Home") is None

    # Test with trailing slashes, query params etc (Current implementation might fail here if not handled)
    # The current regex uses `twitter\.com/([A-Za-z0-9_]+)`, which extracts the first group matching alphanumeric+underscore.
    # It will extract correctly from paths with query parameters due to how search works.
    assert _extract_twitter_username("https://twitter.com/johndoe?s=21") == "johndoe"
    assert _extract_twitter_username("x.com/johndoe/") == "johndoe"
