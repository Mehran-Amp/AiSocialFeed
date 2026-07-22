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
from urllib.parse import urlparse

import feedparser
import httpx

from bot.models import Platform
from config.settings import config

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            # SEC-6 fix: follow_redirects=False prevents SSRF via redirect.
            # is_safe_url() only validates the initial URL; with follow_redirects=True
            # a malicious server at https://evil.com/feed could 301 → http://redis:6379.
            # Callers that need redirect support must validate the Location header
            # with is_safe_url() before following manually.
            follow_redirects=False,
            headers={"User-Agent": "SocialtoFeed/3.2 (feed aggregator bot)"},
        )
    return _client


async def resolve_account(platform: Platform, raw_input: str) -> Optional[dict]:
    raw_input = raw_input.strip().rstrip("/")

    resolvers = {
        Platform.YOUTUBE:   _resolve_youtube,
        Platform.TWITTER:   _resolve_twitter,
        Platform.INSTAGRAM: _resolve_instagram,
        Platform.RSS:       _resolve_rss,
        Platform.TIKTOK:    _resolve_tiktok,
        Platform.LINKEDIN:  _resolve_linkedin,
        Platform.REDDIT:    _resolve_reddit,
        Platform.TELEGRAM:  _resolve_telegram,
        Platform.BLUESKY:   _resolve_bluesky,
        Platform.MASTODON:  _resolve_mastodon,
        Platform.THREADS:   _resolve_threads,
        Platform.FACEBOOK:  _resolve_facebook,
        Platform.DISCORD:   _resolve_discord,
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


# ─── YouTube (direct official RSS) ───────────

async def _resolve_youtube(raw: str) -> Optional[dict]:
    channel_id = None
    handle = None

    if "youtube.com" in raw or "youtu.be" in raw:
        parsed = urlparse(raw if raw.startswith("http") else f"https://{raw}")
        path = parsed.path.strip("/")
        if path.startswith("channel/"):
            channel_id = path.split("/")[1]
        elif path.startswith("@"):
            handle = path[1:]
        elif path.startswith("c/") or path.startswith("user/"):
            handle = path.split("/", 1)[1]
        else:
            handle = path
    elif raw.startswith("@"):
        handle = raw[1:]
    else:
        handle = raw

    if channel_id:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        name = channel_id
    elif handle:
        channel_id = await _youtube_handle_to_channel_id(handle)
        if not channel_id:
            return None
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        name = handle
    else:
        return None

    client = _get_client()
    try:
        resp = await client.get(feed_url)
        if resp.status_code != 200:
            return None
        feed = feedparser.parse(resp.text)
        name = feed.feed.get("title", name)
        channel_id = feed.feed.get("yt_channelid", channel_id)
    except Exception:
        pass

    return {"identifier": channel_id or handle, "name": name,
            "feed_url": feed_url, "private": False}


async def _youtube_handle_to_channel_id(handle: str) -> Optional[str]:
    client = _get_client()
    try:
        resp = await client.get(f"https://www.youtube.com/@{handle}")
        if resp.status_code == 404:
            return None
        match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', resp.text)
        if match:
            return match.group(1)
        match = re.search(r'channel/(UC[a-zA-Z0-9_-]{22})', resp.text)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning(f"YouTube handle resolve failed for @{handle}: {e}")
    return None


# ─── Twitter/X — via self-hosted RSSHub ──────

async def _resolve_twitter(raw: str) -> Optional[dict]:
    username = _extract_twitter_username(raw)
    if not username:
        return None

    feed_url = f"{config.rsshub.url}/twitter/user/{username}"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", username)
            if "protected" in resp.text.lower():
                return {"identifier": username, "name": username,
                        "feed_url": feed_url, "private": True}
            if feed.entries:
                return {"identifier": username, "name": name,
                        "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"Twitter resolver failed for @{username}: {e}")

    # Return unverified — fetcher will confirm on first fetch
    return {"identifier": username, "name": f"@{username}",
            "feed_url": feed_url, "private": False}


def _extract_twitter_username(raw: str) -> Optional[str]:
    patterns = [
        r"twitter\.com/([A-Za-z0-9_]+)",
        r"x\.com/([A-Za-z0-9_]+)",
        r"@([A-Za-z0-9_]+)",
        r"^([A-Za-z0-9_]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            username = match.group(1)
            if username.lower() not in ("home", "explore", "notifications", "messages"):
                return username
    return None


# ─── Instagram — via self-hosted RSSHub ──────

async def _resolve_instagram(raw: str) -> Optional[dict]:
    username = _extract_instagram_username(raw)
    if not username:
        return None

    feed_url = f"{config.rsshub.url}/instagram/user/{username}"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", username)
            if "private" in resp.text.lower():
                return {"identifier": username, "name": username,
                        "feed_url": feed_url, "private": True}
            return {"identifier": username, "name": name,
                    "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"Instagram resolver failed for @{username}: {e}")

    return {"identifier": username, "name": f"@{username}",
            "feed_url": feed_url, "private": False}


def _extract_instagram_username(raw: str) -> Optional[str]:
    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", raw)
    if match:
        return match.group(1)
    match = re.match(r"@?([A-Za-z0-9_.]+)$", raw)
    if match:
        return match.group(1)
    return None


# ─── RSS (direct) ────────────────────────────

async def _resolve_rss(raw: str) -> Optional[dict]:
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    # Block SSRF: internal Docker services and private IPs
    from bot.utils.url_validator import is_safe_url
    if not is_safe_url(raw):
        return None  # Silently reject — no error details to attacker

    client = _get_client()
    try:
        resp = await client.get(raw, timeout=15.0)
        if resp.status_code != 200:
            return None

        feed = feedparser.parse(resp.text)

        if not feed.get("version") and not feed.entries:
            rss_url = _autodiscover_rss(resp.text, raw)
            if rss_url:
                return await _resolve_rss(rss_url)
            return None

        name = feed.feed.get("title", raw)
        return {"identifier": raw, "name": name, "feed_url": raw, "private": False}
    except Exception as e:
        logger.warning(f"RSS resolve failed for {raw}: {e}")
        return None


def _autodiscover_rss(html: str, base_url: str) -> Optional[str]:
    patterns = [
        r'<link[^>]+type="application/rss\+xml"[^>]+href="([^"]+)"',
        r'<link[^>]+href="([^"]+)"[^>]+type="application/rss\+xml"',
        r'<link[^>]+type="application/atom\+xml"[^>]+href="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                parsed = urlparse(base_url)
                url = f"{parsed.scheme}://{parsed.netloc}{url}"
            return url
    return None


# ─── TikTok — via self-hosted RSSHub ─────────

async def _resolve_tiktok(raw: str) -> Optional[dict]:
    match = re.search(r"tiktok\.com/@?([A-Za-z0-9_.]+)", raw)
    username = match.group(1) if match else raw.lstrip("@")

    feed_url = f"{config.rsshub.url}/tiktok/user/@{username}"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", f"@{username}")
            return {"identifier": username, "name": name,
                    "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"TikTok resolver failed for @{username}: {e}")

    return {"identifier": username, "name": f"@{username}",
            "feed_url": feed_url, "private": False}


# ─── LinkedIn (direct RSS) ───────────────────

async def _resolve_linkedin(raw: str) -> Optional[dict]:
    match = re.search(r"linkedin\.com/company/([A-Za-z0-9_-]+)", raw)
    if not match:
        return None

    company = match.group(1)
    feed_url = f"https://www.linkedin.com/rss/company-updates/{company}/"

    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", company)
            return {"identifier": company, "name": name,
                    "feed_url": feed_url, "private": False}
    except Exception:
        pass
    return None


# ─── Reddit (official RSS) ───────────────────

async def _resolve_reddit(raw: str) -> Optional[dict]:
    match = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)", raw)
    if match:
        subreddit = match.group(1)
    else:
        subreddit = raw.strip("/").split("/")[-1]

    feed_url = f"https://old.reddit.com/r/{subreddit}/.rss"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", f"r/{subreddit}")
            return {"identifier": subreddit, "name": name,
                    "feed_url": feed_url, "private": False}
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            return {"identifier": subreddit, "name": subreddit,
                    "feed_url": feed_url, "private": True}
    except Exception as e:
        logger.warning(f"Reddit resolve failed: {e}")
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


# ─── Bluesky (official public API) ───────────

async def _resolve_bluesky(raw: str) -> Optional[dict]:
    raw = raw.strip().lstrip("@")

    if "bsky.app/profile/" in raw:
        handle = raw.split("bsky.app/profile/")[-1].split("/")[0]
    elif "@" in raw:
        parts = raw.split("@")
        handle = f"{parts[0]}@{parts[1]}" if len(parts) > 1 else parts[0]
    else:
        handle = raw

    client = _get_client()
    try:
        resp = await client.get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
            params={"actor": handle},
            timeout=10.0,
        )
        if resp.status_code in (400, 404):
            return None
        if resp.status_code != 200:
            return None

        data = resp.json()
        display_name = data.get("displayName") or data.get("handle", handle)
        actual_handle = data.get("handle", handle)

        return {"identifier": actual_handle, "name": display_name,
                "feed_url": None, "private": False}
    except Exception as e:
        logger.warning(f"Bluesky resolve failed for {handle}: {e}")
    return None


# ─── Mastodon (direct RSS) ────────────────────

async def _resolve_mastodon(raw: str) -> Optional[dict]:
    raw = raw.strip().lstrip("@")
    feed_url = None
    name = raw

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
            feed_url = f"https://{instance}/@{username}.rss"
            name = f"@{username}@{instance}"
    elif "http" in raw or "/" in raw:
        if not raw.startswith("http"):
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        if path.startswith("@"):
            feed_url = f"{parsed.scheme}://{parsed.netloc}/{path}.rss"
            name = path

    if not feed_url:
        return None

    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=10.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            title = feed.feed.get("title", name)
            return {"identifier": raw, "name": title,
                    "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"Mastodon resolve failed: {e}")
    return None


# ─── Threads — via self-hosted RSSHub ────────

async def _resolve_threads(raw: str) -> Optional[dict]:
    username = None
    match = re.search(r"threads\.(?:net|com)/@?([A-Za-z0-9_.]+)", raw)
    if match:
        username = match.group(1)
    elif raw.startswith("@"):
        username = raw[1:]
    else:
        username = raw.strip()

    if not username:
        return None

    feed_url = f"{config.rsshub.url}/threads/user/{username}"
    client = _get_client()
    try:
        resp = await client.get(f"https://www.threads.net/@{username}", timeout=10.0)
        if resp.status_code == 404:
            return None
        name_match = re.search(r'<meta property="og:title" content="([^"]+)"', resp.text)
        name = name_match.group(1) if name_match else f"@{username}"
        is_private = "This account is private" in resp.text
        return {"identifier": username, "name": name,
                "feed_url": feed_url, "private": is_private}
    except Exception as e:
        logger.warning(f"Threads resolve failed for @{username}: {e}")

    return {"identifier": username, "name": f"@{username}",
            "feed_url": feed_url, "private": False}


# ─── Facebook — via self-hosted RSSHub ───────

async def _resolve_facebook(raw: str) -> Optional[dict]:
    match = re.search(r"facebook\.com/([^/?\s]+)", raw)
    page = match.group(1) if match else raw.lstrip("@")

    feed_url = f"{config.rsshub.url}/facebook/page/{page}"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", page)
            return {"identifier": page, "name": name,
                    "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"Facebook resolver failed for {page}: {e}")

    return {"identifier": page, "name": page,
            "feed_url": feed_url, "private": False}


# ─── Discord — via self-hosted RSSHub ────────

async def _resolve_discord(raw: str) -> Optional[dict]:
    match = re.search(r"discord\.com/channels/([0-9]+)/([0-9]+)", raw)
    if match:
        server_id, channel_id = match.group(1), match.group(2)
    elif "/" in raw:
        parts = raw.split("/", 1)
        server_id, channel_id = parts[0].strip(), parts[1].strip()
    else:
        return None

    identifier = f"{server_id}/{channel_id}"
    feed_url = f"{config.rsshub.url}/discord/channel/{server_id}/{channel_id}"
    client = _get_client()
    try:
        resp = await client.get(feed_url, timeout=15.0)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.text)
            name = feed.feed.get("title", f"Discord {channel_id}")
            return {"identifier": identifier, "name": name,
                    "feed_url": feed_url, "private": False}
    except Exception as e:
        logger.warning(f"Discord resolver failed for {identifier}: {e}")

    return {"identifier": identifier, "name": f"Discord #{channel_id}",
            "feed_url": feed_url, "private": False}
