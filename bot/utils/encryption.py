"""
SocialtoFeed — Encryption Utility
Fernet symmetric encryption for sensitive values (API keys, etc.)
"""

import base64
import hashlib
from cryptography.fernet import Fernet
from config.settings import config


def _get_fernet() -> Fernet:
    """Derive a valid Fernet key from the configured ENCRYPTION_KEY."""
    raw = config.security.encryption_key.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    """Encrypt a plaintext string. Returns base64 ciphertext."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext."""
    return _get_fernet().decrypt(value.encode()).decode()


def mask(value: str, visible: int = 6) -> str:
    """Mask a sensitive string for display. e.g. sk-abc•••••••••xyz"""
    if not value or len(value) <= visible * 2:
        return "•" * 8
    return value[:visible] + "•" * (len(value) - visible * 2) + value[-visible:]
