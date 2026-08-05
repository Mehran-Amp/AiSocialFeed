"""
SocialtoFeed — Platform Fetchers v3.2
All social platforms fetched via stable sources.
Strategy:
  Free:    YouTube, Twitter/X, RSS, Reddit, Telegram  — direct/official
  Pro:     + Instagram, LinkedIn, Threads, Bluesky, Mastodon
  Premium: + TikTok, Facebook, Discord
Twitter/Instagram/TikTok/Threads/Facebook/Discord → self-hosted RSSHub + cookies
"""

from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import httpx

from bot.models import Account, Platform
from bot.platforms.base import BasePlatformFetcher, FetchResult, FetchedPost
from config.settings import config

logger = logging.getLogger(__name__)

# ─── Plan → Platform Access ───────────────────
PLAN_PLATFORMS = {
    "free": [Platform.TELEGRAM],
    "pro":  [Platform.TELEGRAM],
    "premium": [Platform.TELEGRAM],
}

PLATFORM_LABELS = {
    Platform.TELEGRAM:  "✈️ Telegram",
}

def get_allowed_platforms(plan: str) -> list:
    return PLAN_PLATFORMS.get(plan, PLAN_PLATFORMS["free"])

def is_platform_allowed(platform: Platform, plan: str) -> bool:
    return platform in get_allowed_platforms(plan)

# ─── Shared HTTP client ───────────────────────
_http: Optional[httpx.AsyncClient] = None

def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(
            timeout=20.0, follow_redirects=True,
            headers={"User-Agent": "SocialtoFeed/3.2 (feed aggregator)"},
        )
    return _http

# ─── Helpers ─────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    import time
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime.fromtimestamp(time.mktime(val), tz=timezone.utc)
            except Exception:
                pass
    return None

def _entry_video(entry) -> Optional[str]:
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("video/"):
            return enc.get("url") or enc.get("href")
    return None

def _entry_image(entry) -> Optional[str]:
    media = getattr(entry, "media_thumbnail", None)
    if media and isinstance(media, list) and media:
        return media[0].get("url")
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image/"):
            return enc.get("url") or enc.get("href")
    return None

def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()

async def _fetch_feed(url: str) -> Optional[feedparser.FeedParserDict]:
    resp = await _client().get(url)
    if resp.status_code in (403, 404):
        return None
    if resp.status_code != 200:
        raise httpx.HTTPStatusError(
            f"HTTP {resp.status_code}", request=resp.request, response=resp
        )
    return feedparser.parse(resp.text)

# ─── RSSHub fetch with cookie injection ──────

# Module-level Redis client for cookie lookups — reused across fetches
from bot.cache import get_redis as _cookie_redis_client  # PERF-4: shared pool


async def _get_cookie(platform: str) -> str:
    """
    Get RSSHub cookie. Checks Redis first (admin panel), falls back to .env.
    Uses a module-level connection — no new Redis connection per fetch.
    """
    try:
        r = await _cookie_redis_client()
        redis_cookie = await r.get(f"rsshub:cookie:{platform}")
        if redis_cookie:
            return redis_cookie
    except Exception:
        pass
    fallbacks = {
        "twitter":   config.rsshub.cookie_twitter,
        "instagram": config.rsshub.cookie_instagram,
        "tiktok":    config.rsshub.cookie_tiktok,
    }
    return fallbacks.get(platform, "")
async def _fetch_rsshub(url: str) -> Optional[feedparser.FeedParserDict]:
    """
    Fetch RSS from self-hosted RSSHub with session cookie injection.
    Cookies are read from Redis (admin panel) or .env as fallback.
    No restart needed when cookies are updated from admin panel.
    """
    headers = {}
    platform = None
    if "twitter" in url:   platform = "twitter"
    elif "instagram" in url: platform = "instagram"
    elif "tiktok" in url:  platform = "tiktok"

    if platform:
        cookie = await _get_cookie(platform)
        if cookie:
            headers["Cookie"] = cookie

    try:
        resp = await _client().get(url, headers=headers, timeout=20.0)
        if resp.status_code in (403, 404):
            return None
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp
            )
        return feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"RSSHub fetch failed {url}: {e}")
        return None

def _parse_entries(feed: feedparser.FeedParserDict) -> list:
    """Convert feedparser entries to FetchedPost list. Shared by all RSSHub fetchers."""
    posts = []
    for entry in feed.entries[:10]:
        url = entry.get("link", "")
        summary = entry.get("summary", "")
        image_url = _entry_image(entry)
        if not image_url:
            m = re.search(r'<img[^>]+src="([^"]+)"', summary)
            if m:
                image_url = m.group(1)
        video_url = _entry_video(entry)
        posts.append(FetchedPost(
            post_id=entry.get("id") or url,
            title=_strip_html(entry.get("title", ""))[:200],
            url=url,
            published_at=_parse_date(entry),
            description=_strip_html(summary)[:4000],
            image_url=image_url,
            video_url=video_url,
            has_video=bool(video_url) or "video" in summary.lower() or "mp4" in url.lower(),
            author="",
        ))
    return posts

# ─── Instant View helper ─────────────────────

def make_instant_view_button(url: str, lang: str = "en"):
    """
    Generate a Telegram Instant View button for article URLs.

    Requires TELEGRAM_IV_RHASH to be set in .env.
    Generate your rhash at https://instantview.telegram.org

    Returns None if rhash is not configured — callers must handle None.
    """
    from config.settings import config as _cfg
    rhash = _cfg.telegram.iv_rhash
    if not rhash:
        # IV not configured — button silently disabled
        return None

    from telegram import InlineKeyboardButton
    iv_url = f"https://t.me/iv?url={url}&rhash={rhash}"
    labels = {
        "fa": "📖 خواندن مقاله",
        "ar": "📖 اقرأ المقال",
        "ru": "📖 Читать статью",
        "tr": "📖 Makaleyi oku",
        "zh": "📖 阅读全文",
    }
    label = labels.get(lang, "📖 Read full article")
    return InlineKeyboardButton(label, url=iv_url)



# ─── Telegram Channel (Free) ─────────────────

class TelegramChannelFetcher(BasePlatformFetcher):
    platform = Platform.TELEGRAM

    async def fetch_posts(self, account: Account) -> FetchResult:
        username = account.identifier.lstrip("@")
        url = f"{config.rsshub.url}/telegram/channel/{username}"
        try:
            feed = await _fetch_rsshub(url)
            if feed is None:
                return FetchResult(account_not_found=True)
            if not feed.entries:
                return FetchResult(posts=[])

            # The RSSHub feed contains HTML in the description.
            # We want to preserve the HTML and media correctly.
            posts = []
            for entry in reversed(feed.entries[:10]):
                post_url = entry.get("link", "")

                # Title is usually text, description contains the HTML payload
                title = entry.get("title", "Message")

                # Description contains the HTML. We do NOT strip HTML this time!
                description = entry.get("description", "")

                # Check for media enclosures or tags
                image_url = _entry_image(entry)
                video_url = _entry_video(entry)

                if not image_url:
                    m = re.search(r'<img[^>]+src="([^"]+)"', description)
                    if m:
                        image_url = m.group(1)

                if not video_url:
                    m = re.search(r'<video[^>]+src="([^"]+)"', description)
                    if m:
                        video_url = m.group(1)

                has_video = bool(video_url) or "video" in description.lower() or "mp4" in description.lower()

                # We save the raw description so post_formatter can use it.
                # However, feedparser entries might have HTML directly in description.
                # Let's save it.

                posts.append(FetchedPost(
                    post_id=entry.get("id") or post_url,
                    title=_strip_html(title)[:100],
                    url=post_url,
                    published_at=_parse_date(entry),
                    description=description, # preserve HTML
                    image_url=image_url,
                    video_url=video_url,
                    has_video=has_video,
                    author=account.display_name or username,
                ))
            return FetchResult(posts=posts)
        except Exception as e:
            logger.warning(f"TelegramChannelFetcher RSSHub error: {e}")
            return FetchResult(error=str(e), platform_down=True)

# ─── Registry — ALL platforms registered ─────

PLATFORM_FETCHERS: dict = {
    Platform.TELEGRAM:  TelegramChannelFetcher,
}

def get_fetcher(platform: Platform) -> BasePlatformFetcher:
    cls = PLATFORM_FETCHERS.get(platform)
    if not cls:
        raise ValueError(f"No fetcher for platform: {platform}")
    return cls()
