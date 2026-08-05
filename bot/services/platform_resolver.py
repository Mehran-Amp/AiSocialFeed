"""
SocialtoFeed — Platform Resolver v3.2
All resolvers updated to use self-hosted RSSHub for:
Twitter, Instagram, TikTok, Threads, Facebook, Discord
Direct/official sources for:
YouTube, RSS, Reddit, LinkedIn, Telegram, Bluesky, Mastodon
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse, urljoin

import feedparser
import httpx

from bot.models import Platform
from config.settings import config

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def _create_client() -> httpx.AsyncClient:
    """Create a new AsyncClient with predefined configuration."""
    return httpx.AsyncClient(
        timeout=15.0,
        # SEC-6 fix: follow_redirects=False prevents SSRF via redirect.
        # is_safe_url() only validates the initial URL; with follow_redirects=True
        # a malicious server at https://evil.com/feed could 301 → http://redis:6379.
        # Callers that need redirect support must validate the Location header
        # with is_safe_url() before following manually.
        follow_redirects=False,
        headers={"User-Agent": "SocialtoFeed/3.2 (feed aggregator bot)"},
    )


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = _create_client()
    return _client


async def resolve_account(platform: Platform, raw_input: str) -> Optional[dict]:
    raw_input = raw_input.strip().rstrip("/")

    resolvers = {
        Platform.TELEGRAM:  _resolve_telegram,
    }

    resolver = resolvers.get(platform)
    if not resolver:
        logger.warning(f"No resolver for platform: {platform}")
        return None

    try:
        return await resolver(raw_input)
    except httpx.TimeoutException:
        logger.warning(f"Timeout resolving {platform.value}: {raw_input}")
        return None
    except Exception as e:
        logger.error(f"Error resolving {platform.value} '{raw_input}': {e}")
        return None


# ─── Telegram Channel ─────────────────────────

async def _resolve_telegram(raw: str) -> Optional[dict]:
    match = re.search(r"t\.me/([A-Za-z0-9_]+)", raw)
    username = match.group(1) if match else raw.lstrip("@").strip()

    if not username:
        return None

    client = _get_client()
    try:
        resp = await client.get(f"https://t.me/{username}", timeout=10.0)
        if resp.status_code == 200:
            title_match = re.search(r'<meta property="og:title" content="([^"]+)"', resp.text)
            name = title_match.group(1) if title_match else username
            return {"identifier": username, "name": name,
                    "feed_url": None, "private": False}
        elif resp.status_code == 404:
            return None
    except Exception as e:
        logger.warning(f"Telegram channel resolve failed for @{username}: {e}")
    return None


