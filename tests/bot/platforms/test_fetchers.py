import pytest
from unittest.mock import patch

from bot.platforms.fetchers import make_instant_view_button
from config import config

def test_make_instant_view_button_no_rhash():
    """Test button generation when rhash is not configured."""
    with patch.object(config.telegram, "iv_rhash", None):
        result = make_instant_view_button("https://example.com/article")
        assert result is None

def test_make_instant_view_button_with_rhash_default_lang():
    """Test button generation with configured rhash and default language."""
    test_url = "https://example.com/article"
    test_rhash = "test_rhash_123"

    with patch.object(config.telegram, "iv_rhash", test_rhash):
        result = make_instant_view_button(test_url)

        assert result is not None
        assert result.text == "📖 Read full article"
        assert result.url == f"https://t.me/iv?url={test_url}&rhash={test_rhash}"

@pytest.mark.parametrize("lang, expected_label", [
    ("fa", "📖 خواندن مقاله"),
    ("ar", "📖 اقرأ المقال"),
    ("ru", "📖 Читать статью"),
    ("tr", "📖 Makaleyi oku"),
    ("zh", "📖 阅读全文"),
    ("unknown", "📖 Read full article"),
])
def test_make_instant_view_button_with_rhash_custom_lang(lang, expected_label):
    """Test button generation with configured rhash and specific languages."""
    test_url = "https://example.com/article"
    test_rhash = "test_rhash_123"

    with patch.object(config.telegram, "iv_rhash", test_rhash):
        result = make_instant_view_button(test_url, lang=lang)

        assert result is not None
        assert result.text == expected_label
        assert result.url == f"https://t.me/iv?url={test_url}&rhash={test_rhash}"
