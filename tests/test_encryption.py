import pytest
from unittest.mock import patch, MagicMock
from bot.utils.encryption import encrypt

@patch("bot.utils.encryption._get_fernet")
def test_encrypt_predictable_output(mock_get_fernet):
    # Setup mock to return a predictable string
    mock_fernet_instance = MagicMock()
    mock_fernet_instance.encrypt.return_value = b"mocked_encrypted_bytes"
    mock_get_fernet.return_value = mock_fernet_instance

    # Call the function
    original = "my_secret"
    result = encrypt(original)

    # Assert predictable output and proper encoding/decoding
    assert result == "mocked_encrypted_bytes"
    mock_fernet_instance.encrypt.assert_called_once_with(b"my_secret")
