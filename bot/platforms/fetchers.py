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
    "free": [Platform.YOUTUBE, Platform.TWITTER, Platform.RSS,
             Platform.REDDIT, Platform.TELEGRAM],
    "pro":  [Platform.YOUTUBE, Platform.TWITTER, Platform.RSS, Platform.REDDIT,
             Platform.TELEGRAM, Platform.INSTAGRAM, Platform.LINKEDIN,
             Platform.THREADS, Platform.BLUESKY, Platform.MASTODON],
    "premium": [Platform.YOUTUBE, Platform.TWITTER, Platform.RSS, Platform.REDDIT,
                Platform.TELEGRAM, Platform.INSTAGRAM, Platform.LINKEDIN,
                Platform.THREADS, Platform.BLUESKY, Platform.MASTODON,
                Platform.TIKTOK, Platform.FACEBOOK, Platform.DISCORD],
}

PLATFORM_LABELS = {
    Platform.YOUTUBE:   "🎬 YouTube",
    Platform.TWITTER:   "🐦 Twitter/X",
    Platform.INSTAGRAM: "📸 Instagram",
    Platform.RSS:       "📡 RSS",
    Platform.TIKTOK:    "🎵 TikTok",
    Platform.LINKEDIN:  "💼 LinkedIn",
    Platform.REDDIT:    "🤖 Reddit",
    Platform.TELEGRAM:  "✈️ Telegram",
    Platform.BLUESKY:   "🦋 Bluesky",
    Platform.MASTODON:  "🐘 Mastodon",
    Platform.THREADS:   "🧵 Threads",
    Platform.FACEBOOK:  "👥 Facebook",
    Platform.DISCORD:   "🎮 Discord",
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
        posts.append(FetchedPost(
            post_id=entry.get("id") or url,
            title=_strip_html(entry.get("title", ""))[:200],
            url=url,
            published_at=_parse_date(entry),
            description=_strip_html(summary)[:500],
            image_url=image_url,
            has_video="video" in summary.lower() or "mp4" in url.lower(),
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


# ─── YouTube (Free) ──────────────────────────

class YouTubeFetcher(BasePlatformFetcher):
    platform = Platform.YOUTUBE

    async def fetch_posts(self, account: Account) -> FetchResult:
        if not account.feed_url:
            return FetchResult(error="No feed URL")
        try:
            feed = await _fetch_feed(account.feed_url)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        if feed is None:
            return FetchResult(account_not_found=True)
        posts = []
        for entry in feed.entries[:10]:
            url = entry.get("link", "")
            if not url:
                continue
            video_id = entry.get("yt_videoid", "")
            thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else None
            posts.append(FetchedPost(
                post_id=entry.get("id") or url,
                title=entry.get("title", "No title"),
                url=url,
                published_at=_parse_date(entry),
                description=_strip_html(entry.get("summary", ""))[:500],
                image_url=thumbnail,
                has_video=True,
                author=entry.get("author", account.display_name),
            ))
        return FetchResult(posts=posts)

# ─── RSS (Free) ──────────────────────────────

class RSSFetcher(BasePlatformFetcher):
    platform = Platform.RSS

    async def fetch_posts(self, account: Account) -> FetchResult:
        url = account.feed_url or account.identifier
        try:
            feed = await _fetch_feed(url)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        if feed is None:
            return FetchResult(account_not_found=True)
        if not feed.get("version") and not feed.entries:
            return FetchResult(error="Not a valid RSS feed")
        posts = []
        for entry in feed.entries[:15]:
            post_url = entry.get("link", "") or entry.get("id", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            has_video = any(
                enc.get("type", "").startswith("video/")
                for enc in getattr(entry, "enclosures", [])
            )
            posts.append(FetchedPost(
                post_id=entry.get("id") or post_url,
                title=entry.get("title", "No title")[:256],
                url=post_url,
                published_at=_parse_date(entry),
                description=_strip_html(summary)[:500],
                image_url=_entry_image(entry),
                has_video=has_video,
                author=entry.get("author", ""),
            ))
        return FetchResult(posts=posts)

# ─── Reddit (Free) ───────────────────────────

class RedditFetcher(BasePlatformFetcher):
    platform = Platform.REDDIT

    async def fetch_posts(self, account: Account) -> FetchResult:
        url = f"https://old.reddit.com/r/{account.identifier}/.rss"
        try:
            feed = await _fetch_feed(url)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        if feed is None:
            return FetchResult(account_private=True)
        posts = []
        for entry in feed.entries[:10]:
            entry_url = entry.get("link", "")
            summary = _strip_html(entry.get("summary", ""))[:400]
            has_video = "v.redd.it" in entry_url or "v.redd.it" in summary
            posts.append(FetchedPost(
                post_id=entry.get("id") or entry_url,
                title=entry.get("title", "")[:256],
                url=entry_url,
                published_at=_parse_date(entry),
                description=summary,
                image_url=_entry_image(entry),
                has_video=has_video,
                author=entry.get("author", ""),
            ))
        return FetchResult(posts=posts)

# ─── Twitter/X (Free) — via self-hosted RSSHub ──

class TwitterFetcher(BasePlatformFetcher):
    platform = Platform.TWITTER

    async def fetch_posts(self, account: Account) -> FetchResult:
        url = f"{config.rsshub.url}/twitter/user/{account.identifier}"
        try:
            feed = await _fetch_rsshub(url)
            if feed and feed.entries:
                posts = _parse_entries(feed)
                for p in posts:
                    if any(kw in (p.description or "").lower() for kw in ["video", "gif", "mp4"]):
                        p.has_video = True
                return FetchResult(posts=posts)
            return FetchResult(error="No posts returned", platform_down=True)
        except Exception as e:
            logger.warning(f"TwitterFetcher error: {e}")
            return FetchResult(error=str(e), platform_down=True)

# ─── Instagram (Pro) — via self-hosted RSSHub ──

class InstagramFetcher(BasePlatformFetcher):
    platform = Platform.INSTAGRAM

    async def fetch_posts(self, account: Account) -> FetchResult:
        url = f"{config.rsshub.url}/instagram/user/{account.identifier}"
        try:
            feed = await _fetch_rsshub(url)
            if feed and feed.entries:
                posts = _parse_entries(feed)
                for p in posts:
                    if "/reel/" in (p.url or ""):
                        p.has_video = True
                return FetchResult(posts=posts)
            return FetchResult(error="No posts returned", platform_down=True)
        except Exception as e:
            logger.warning(f"InstagramFetcher error: {e}")
            return FetchResult(error=str(e), platform_down=True)

# ─── LinkedIn (Pro) — direct RSS ─────────────

class LinkedInFetcher(BasePlatformFetcher):
    platform = Platform.LINKEDIN

    async def fetch_posts(self, account: Account) -> FetchResult:
        # LinkedIn removed their public RSS in 2020 — route via RSSHub.
        # Must use _fetch_rsshub (not _fetch_feed) so cookie/session headers
        # are injected; otherwise RSSHub returns 403.
        url = f"{config.rsshub.url}/linkedin/company/{account.identifier}"
        try:
            feed = await _fetch_rsshub(url)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        if feed is None:
            return FetchResult(account_not_found=True)
        posts = []
        for entry in feed.entries[:10]:
            entry_url = entry.get("link", "")
            posts.append(FetchedPost(
                post_id=entry.get("id") or entry_url,
                title=_strip_html(entry.get("title", ""))[:256],
                url=entry_url,
                published_at=_parse_date(entry),
                description=_strip_html(entry.get("summary", ""))[:500],
                image_url=_entry_image(entry),
            ))
        return FetchResult(posts=posts)

# ─── Telegram Channel (Free) ─────────────────

class TelegramChannelFetcher(BasePlatformFetcher):
    platform = Platform.TELEGRAM

    async def fetch_posts(self, account: Account) -> FetchResult:
        username = account.identifier.lstrip("@")
        url = f"https://t.me/s/{username}"
        try:
            resp = await _client().get(url)
            if resp.status_code == 404:
                return FetchResult(account_not_found=True)
            if resp.status_code != 200:
                return FetchResult(error=f"HTTP {resp.status_code}", platform_down=True)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        posts = self._parse_tme(resp.text, username)
        return FetchResult(posts=posts)

    def _parse_tme(self, html: str, username: str) -> list:
        posts = []
        blocks = re.findall(
            r'<div class="tgme_widget_message_wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            html, re.DOTALL,
        )
        for block in reversed(blocks[-10:]):
            id_match = re.search(r'data-post="[^/]+/(\d+)"', block)
            msg_id = id_match.group(1) if id_match else ""
            post_url = f"https://t.me/{username}/{msg_id}" if msg_id else ""
            text_match = re.search(
                r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL
            )
            text = _strip_html(text_match.group(1))[:500] if text_match else ""
            img_match = re.search(r"background-image:url\('([^']+)'\)", block)
            image_url = img_match.group(1) if img_match else None
            has_video = "tgme_widget_message_video" in block
            date_match = re.search(r'datetime="([^"]+)"', block)
            pub_date = None
            if date_match:
                try:
                    pub_date = datetime.fromisoformat(date_match.group(1))
                except Exception:
                    pass
            if not text and not post_url:
                continue
            posts.append(FetchedPost(
                post_id=msg_id or post_url,
                title=text[:100] or "Message",
                url=post_url,
                published_at=pub_date,
                description=text,
                image_url=image_url,
                has_video=has_video,
            ))
        return posts

# ─── TikTok (Premium) — via self-hosted RSSHub ──

class TikTokFetcher(BasePlatformFetcher):
    platform = Platform.TIKTOK

    async def fetch_posts(self, account: Account) -> FetchResult:
        username = account.identifier.lstrip("@")
        url = f"{config.rsshub.url}/tiktok/user/@{username}"
        try:
            feed = await _fetch_rsshub(url)
            if feed and feed.entries:
                posts = _parse_entries(feed)
                for p in posts:
                    p.has_video = True  # TikTok is always video
                return FetchResult(posts=posts)
            return FetchResult(error="No posts returned", platform_down=True)
        except Exception as e:
            logger.warning(f"TikTokFetcher error: {e}")
            return FetchResult(error=str(e), platform_down=True)

# ─── Threads (Pro) — via self-hosted RSSHub ──

class ThreadsFetcher(BasePlatformFetcher):
    platform = Platform.THREADS

    async def fetch_posts(self, account: Account) -> FetchResult:
        url = f"{config.rsshub.url}/threads/user/{account.identifier}"
        try:
            feed = await _fetch_rsshub(url)
            if feed and feed.entries:
                return FetchResult(posts=_parse_entries(feed))
            return FetchResult(error="No posts returned", platform_down=True)
        except Exception as e:
            logger.warning(f"ThreadsFetcher error: {e}")
            return FetchResult(error=str(e), platform_down=True)

# ─── Bluesky (Pro) — official public API ─────

class BlueskyFetcher(BasePlatformFetcher):
    platform = Platform.BLUESKY

    async def fetch_posts(self, account: Account) -> FetchResult:
        handle = account.identifier.lstrip("@")
        url = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
        params = {"actor": handle, "limit": 10, "filter": "posts_no_replies"}
        try:
            resp = await _client().get(url, params=params)
            if resp.status_code == 404:
                return FetchResult(account_not_found=True)
            if resp.status_code != 200:
                return FetchResult(error=f"HTTP {resp.status_code}", platform_down=True)
            data = resp.json()
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)

        posts = []
        for item in data.get("feed", []):
            post = item.get("post", {})
            record = post.get("record", {})
            author = post.get("author", {})
            uri = post.get("uri", "")
            rkey = uri.split("/")[-1] if uri else ""
            post_handle = author.get("handle", handle)
            post_url = f"https://bsky.app/profile/{post_handle}/post/{rkey}" if rkey else ""
            text = record.get("text", "")[:500]
            embed = post.get("embed", {})
            image_url = None
            has_video = False
            embed_type = embed.get("$type", "")
            if "images" in embed_type:
                images = embed.get("images", [])
                if images:
                    image_url = images[0].get("thumb", "")
            elif "video" in embed_type:
                has_video = True
                image_url = embed.get("thumbnail", "")
            created_at = record.get("createdAt", "")
            pub_date = None
            if created_at:
                try:
                    pub_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except Exception:
                    pass
            if not post_url:
                continue
            posts.append(FetchedPost(
                post_id=uri or post_url,
                title=text[:100] or "Post",
                url=post_url,
                published_at=pub_date,
                description=text,
                image_url=image_url,
                has_video=has_video,
                author=author.get("displayName") or post_handle,
            ))
        return FetchResult(posts=posts)

# ─── Mastodon (Pro) — direct RSS ─────────────

class MastodonFetcher(BasePlatformFetcher):
    platform = Platform.MASTODON

    async def fetch_posts(self, account: Account) -> FetchResult:
        feed_url = self._build_feed_url(account.identifier)
        if not feed_url:
            return FetchResult(error="Invalid Mastodon identifier")
        try:
            feed = await _fetch_feed(feed_url)
        except Exception as e:
            return FetchResult(error=str(e), platform_down=True)
        if feed is None:
            return FetchResult(account_not_found=True)
        posts = []
        for entry in feed.entries[:10]:
            entry_url = entry.get("link", "")
            summary = entry.get("summary", "")
            clean = _strip_html(summary)[:500]
            image_url = _entry_image(entry)
            if not image_url:
                m = re.search(r'<img[^>]+src="([^"]+)"', summary)
                if m:
                    image_url = m.group(1)
            has_video = "video" in summary.lower() or any(
                enc.get("type", "").startswith("video/")
                for enc in getattr(entry, "enclosures", [])
            )
            posts.append(FetchedPost(
                post_id=entry.get("id") or entry_url,
                title=clean[:100] or "Post",
                url=entry_url,
                published_at=_parse_date(entry),
                description=clean,
                image_url=image_url,
                has_video=has_video,
                author=account.display_name,
            ))
        return FetchResult(posts=posts)

    def _build_feed_url(self, identifier: str) -> Optional[str]:
        raw = identifier.strip().lstrip("@")
        at_pos = raw.find("@")
        slash_pos = raw.find("/")
        is_user_at_instance = (
            "@" in raw and
            not raw.startswith("http") and
            (slash_pos == -1 or at_pos < slash_pos)
        )
        if is_user_at_instance:
            parts = raw.split("@", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                username, instance = parts
                return f"https://{instance}/@{username}.rss"
        if "http" in raw or "/" in raw:
            if not raw.startswith("http"):
                raw = f"https://{raw}"
            parsed = urlparse(raw)
            path = parsed.path.strip("/")
            if path.startswith("@"):
                return f"{parsed.scheme}://{parsed.netloc}/{path}.rss"
        return None

# ─── Facebook (Premium) — via self-hosted RSSHub ──

class FacebookFetcher(BasePlatformFetcher):
    platform = Platform.FACEBOOK

    async def fetch_posts(self, account: Account) -> FetchResult:
        raw = account.identifier.strip()
        m = re.search(r'facebook\.com/([^/?\s]+)', raw)
        page = m.group(1) if m else raw.lstrip("@")
        try:
            feed = await _fetch_rsshub(f"{config.rsshub.url}/facebook/page/{page}")
            if feed is None:
                return FetchResult(account_not_found=True)
            return FetchResult(posts=_parse_entries(feed))
        except Exception as e:
            return FetchResult(error=str(e)[:200], platform_down=True)

# ─── Discord (Premium) — via self-hosted RSSHub ──

class DiscordFetcher(BasePlatformFetcher):
    platform = Platform.DISCORD

    async def fetch_posts(self, account: Account) -> FetchResult:
        raw = account.identifier.strip()
        m = re.search(r'discord\.com/channels/([0-9]+)/([0-9]+)', raw)
        if m:
            server_id, channel_id = m.group(1), m.group(2)
        elif "/" in raw:
            parts = raw.split("/", 1)
            server_id, channel_id = parts[0].strip(), parts[1].strip()
        else:
            return FetchResult(error="Format: SERVER_ID/CHANNEL_ID")
        try:
            feed = await _fetch_rsshub(
                f"{config.rsshub.url}/discord/channel/{server_id}/{channel_id}"
            )
            if feed is None:
                return FetchResult(account_not_found=True)
            return FetchResult(posts=_parse_entries(feed))
        except Exception as e:
            return FetchResult(error=str(e)[:200], platform_down=True)

# ─── Registry — ALL platforms registered ─────

PLATFORM_FETCHERS: dict = {
    Platform.YOUTUBE:   YouTubeFetcher,
    Platform.TWITTER:   TwitterFetcher,
    Platform.INSTAGRAM: InstagramFetcher,
    Platform.RSS:       RSSFetcher,
    Platform.TIKTOK:    TikTokFetcher,
    Platform.LINKEDIN:  LinkedInFetcher,
    Platform.REDDIT:    RedditFetcher,
    Platform.TELEGRAM:  TelegramChannelFetcher,
    Platform.BLUESKY:   BlueskyFetcher,
    Platform.MASTODON:  MastodonFetcher,
    Platform.THREADS:   ThreadsFetcher,
    Platform.FACEBOOK:  FacebookFetcher,   # ← fixed
    Platform.DISCORD:   DiscordFetcher,    # ← fixed
}

def get_fetcher(platform: Platform) -> BasePlatformFetcher:
    cls = PLATFORM_FETCHERS.get(platform)
    if not cls:
        raise ValueError(f"No fetcher for platform: {platform}")
    return cls()
