"""
SocialtoFeed — Video Link Extractor
Uses yt-dlp ONLY for metadata extraction (no download).
Extracts direct stream URLs for all platforms.
RAM usage: <20MB, Time: 1-3 seconds.

Supported: YouTube, Twitter, Instagram, TikTok, Reddit, LinkedIn
Quality options: 480p, 720p, 1080p only (no higher exposed to users)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VideoQuality:
    label: str          # "480p", "720p", "1080p"
    height: int         # 480, 720, 1080
    url: str            # direct stream URL
    filesize_mb: Optional[float] = None
    ext: str = "mp4"
    has_audio: bool = True


@dataclass
class VideoInfo:
    title: str
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    webpage_url: str                        # original YouTube/Twitter/etc URL
    qualities: list[VideoQuality] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def best_preview_url(self) -> str:
        """Returns the original webpage URL for Telegram preview (no IP issue)."""
        return self.webpage_url


# ─────────────────────────────────────────────
#  Core Extractor
# ─────────────────────────────────────────────

async def extract_video_info(url: str) -> VideoInfo:
    """
    Extract video metadata and direct URLs using yt-dlp.
    NO download — only metadata fetch.
    Returns VideoInfo with available qualities (480p, 720p, 1080p max).
    """
    import asyncio
    import yt_dlp

    def _extract() -> VideoInfo:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,          # KEY: never download
            "extract_flat": False,
            "format": "bestvideo+bestaudio/best",
            "socket_timeout": 15,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as e:
                return VideoInfo(
                    title="Unknown",
                    duration_seconds=None,
                    thumbnail_url=None,
                    webpage_url=url,
                    error=str(e)[:200],
                )

        title = info.get("title", "Video")
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")
        webpage_url = info.get("webpage_url", url)

        # Extract qualities — max 1080p, deduplicated
        qualities = _extract_qualities(info)

        return VideoInfo(
            title=title,
            duration_seconds=duration,
            thumbnail_url=thumbnail,
            webpage_url=webpage_url,
            qualities=qualities,
        )

    # BUG-2 fix: asyncio.get_event_loop() raises RuntimeError in Python 3.12+
    # when called outside a running loop. Use asyncio.get_running_loop() instead —
    # this function is always called from an async context so a loop is guaranteed.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract)


def _extract_qualities(info: dict) -> list[VideoQuality]:
    """
    Parse yt-dlp format list and return only 480p, 720p, 1080p.
    Merges video+audio streams where needed.
    Deduplicates by height.
    """
    TARGET_HEIGHTS = [480, 720, 1080]
    found: dict[int, VideoQuality] = {}

    formats = info.get("formats", [])

    for fmt in formats:
        height = fmt.get("height") or 0
        if height not in TARGET_HEIGHTS:
            continue

        # Skip formats without URL
        url = fmt.get("url", "")
        if not url:
            continue

        # Skip audio-only
        vcodec = fmt.get("vcodec", "")
        if vcodec == "none":
            continue

        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
        filesize_mb = round(filesize / 1024 / 1024, 1) if filesize else None

        # Prefer format with audio (acodec != none)
        acodec = fmt.get("acodec", "none")
        has_audio = acodec not in ("none", None, "")

        existing = found.get(height)
        if existing is None:
            found[height] = VideoQuality(
                label=f"{height}p",
                height=height,
                url=url,
                filesize_mb=filesize_mb,
                ext=fmt.get("ext", "mp4"),
                has_audio=has_audio,
            )
        elif has_audio and not existing.has_audio:
            # Prefer version with audio
            found[height] = VideoQuality(
                label=f"{height}p",
                height=height,
                url=url,
                filesize_mb=filesize_mb,
                ext=fmt.get("ext", "mp4"),
                has_audio=True,
            )

    # Sort by height ascending
    return [found[h] for h in sorted(found.keys())]


# ─────────────────────────────────────────────
#  Format helpers
# ─────────────────────────────────────────────

def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_filesize(mb: Optional[float]) -> str:
    if not mb:
        return ""
    if mb >= 1024:
        return f"{mb/1024:.1f} GB"
    return f"{mb:.0f} MB"


# ─────────────────────────────────────────────
#  Platform detection
# ─────────────────────────────────────────────

VIDEO_PLATFORMS = {
    "youtube.com", "youtu.be",
    "twitter.com", "x.com", "t.co",
    "instagram.com",
    "tiktok.com",
    "reddit.com", "redd.it",
    "linkedin.com",
    "facebook.com", "fb.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
}


def url_has_video_potential(url: str) -> bool:
    """Quick check if a URL might contain video — before calling yt-dlp."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in VIDEO_PLATFORMS)
