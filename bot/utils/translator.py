"""
SocialtoFeed — Translation System
Loads all language JSON files and provides t() lookup function.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# All supported languages — all active from the start
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "🇬🇧 English",
    "fa": "🇮🇷 فارسی",
    "ar": "🇸🇦 العربية",
    "zh": "🇨🇳 中文",
    "de": "🇩🇪 Deutsch",
    "ku": "🏳️ کوردی",
    "hi": "🇮🇳 हिन्दी",
    "ru": "🇷🇺 Русский",
    "tr": "🇹🇷 Türkçe",
    "es": "🇪🇸 Español",
    "id": "🇮🇩 Indonesia",
    "pt": "🇧🇷 Português",
    "fr": "🇫🇷 Français",
    "bn": "🇧🇩 বাংলা",
    "vi": "🇻🇳 Tiếng Việt",
    "th": "🇹🇭 ภาษาไทย",
    "ko": "🇰🇷 한국어",
    "it": "🇮🇹 Italiano",
}

# In-memory store: {"en": {...}, "fa": {...}, ...}
_translations: dict[str, dict] = {}
_translations_dir: str = "/app/translations"


def load_translations(translations_dir: str = "/app/translations") -> None:
    """Load all JSON translation files into memory."""
    global _translations_dir
    _translations_dir = translations_dir

    loaded = []
    for lang_code in SUPPORTED_LANGUAGES:
        path = os.path.join(translations_dir, f"{lang_code}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    _translations[lang_code] = json.load(f)
                loaded.append(lang_code)
            except Exception as e:
                logger.error(f"Failed to load translation '{lang_code}': {e}")
        else:
            logger.warning(f"Translation file missing: {path}")

    # Always fall back to English
    if "en" not in _translations:
        logger.critical("English translation file missing! This is required.")

    logger.info(f"Translations loaded: {', '.join(loaded)}")


def t(key: str, lang: str = "en", **kwargs) -> str:
    """
    Get a translated string by dot-notation key.

    Usage:
        t("menu.add_account", lang="fa")
        t("errors.quota_reached", lang="en", limit=35)
    """
    lang_data = _translations.get(lang) or _translations.get("en", {})
    en_data = _translations.get("en", {})

    # Traverse dot-notation key
    value = _get_nested(lang_data, key)
    if value is None:
        value = _get_nested(en_data, key)
    if value is None:
        logger.warning(f"Missing translation key: '{key}' (lang={lang})")
        return key  # return the key itself as last resort

    if kwargs:
        try:
            return value.format(**kwargs)
        except KeyError:
            return value
    return value


def _get_nested(data: dict, key: str) -> Optional[str]:
    """Navigate nested dict with dot-notation. e.g. 'menu.main.add_account'"""
    keys = key.split(".")
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current if isinstance(current, str) else None


def get_language_name(lang_code: str) -> str:
    return SUPPORTED_LANGUAGES.get(lang_code, lang_code)


def is_rtl(lang_code: str) -> bool:
    """Returns True for right-to-left languages."""
    return lang_code in ("fa", "ar", "ku", "he")
