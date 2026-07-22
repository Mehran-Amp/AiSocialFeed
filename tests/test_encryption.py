import pytest
from cryptography.fernet import InvalidToken
from bot.utils.encryption import encrypt, decrypt, mask

def test_encrypt_decrypt():
    """Test that encrypting and decrypting a string returns the original string."""
    original_text = "secret_api_key_123!"
    encrypted_text = encrypt(original_text)

    assert encrypted_text != original_text
    assert isinstance(encrypted_text, str)

    decrypted_text = decrypt(encrypted_text)
    assert decrypted_text == original_text

def test_encrypt_decrypt_empty_string():
    """Test encrypting and decrypting an empty string."""
    original_text = ""
    encrypted_text = encrypt(original_text)
    decrypted_text = decrypt(encrypted_text)
    assert decrypted_text == original_text

def test_decrypt_invalid_token():
    """Test that decrypting an invalid token raises an exception."""
    with pytest.raises(InvalidToken):
        decrypt("invalid_token_string")

def test_mask():
    """Test the mask utility function."""
    # Normal case: length > 12 (visible*2)
    assert mask("sk-abc123def456xyz789", visible=6) == "sk-abc" + "•" * 9 + "xyz789"

    # Custom visible length
    assert mask("1234567890", visible=2) == "12" + "•" * 6 + "90"

    # Edge case: length <= visible*2
    assert mask("short") == "••••••••"
    assert mask("123456789012") == "••••••••"

    # Edge case: empty string
    assert mask("") == "••••••••"
    assert mask(None) == "••••••••"
