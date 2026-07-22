import pytest
from bot.utils.encryption import mask

def test_mask_empty_or_none():
    """Test masking with None or empty string."""
    assert mask(None) == "••••••••"
    assert mask("") == "••••••••"

def test_mask_short_string():
    """Test masking with a string shorter than visible * 2 (12)."""
    assert mask("12345678901") == "••••••••"

def test_mask_exact_length_string():
    """Test masking with a string length exactly equal to visible * 2 (12)."""
    assert mask("123456789012") == "••••••••"

def test_mask_long_string():
    """Test masking with a string longer than visible * 2 (12)."""
    assert mask("1234567890123") == "123456•890123"
    assert mask("sk-abc123456789xyz") == "sk-abc••••••789xyz"

def test_mask_custom_visible():
    """Test masking with a custom visible parameter."""
    # visible = 2, length = 4 -> 2 * 2 = 4 (should be masked completely)
    assert mask("1234", visible=2) == "••••••••"

    # visible = 2, length = 5
    assert mask("12345", visible=2) == "12•45"

    # visible = 3, length = 10
    assert mask("1234567890", visible=3) == "123••••890"

def test_mask_edge_cases():
    """Test masking with a single visible character."""
    # visible = 1, length = 2 (should be masked)
    assert mask("12", visible=1) == "••••••••"
    # visible = 1, length = 3
    assert mask("123", visible=1) == "1•3"
