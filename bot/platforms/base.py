"""
SocialtoFeed — Base Platform Fetcher
Abstract base class for all platform fetchers.
Handles: deduplication, AI processing, post delivery, error tracking.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bot.models import Account, LogModule, Platform, SentPost, User

logger = logging.getLogger(__name__)


@dataclass
class FetchedPost:
    """Normalized post from any platform."""
    post_id: str              # platform's own ID or URL
    title: str
    url: str
    published_at: Optional[datetime] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    has_video: bool = False
    author: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()

    @property
    def short_description(self) -> str:
        """First 500 chars of description for AI processing."""
        if not self.description:
            return ""
        return self.description[:500]


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    posts: list[FetchedPost] = field(default_factory=list)
    error: Optional[str] = None
    platform_down: bool = False
    account_private: bool = False
    account_not_found: bool = False



# Module-level Redis client for footer post counter
from bot.cache import get_redis as _get_footer_redis  # PERF-4: shared pool

# ── Circuit Breaker constants ─────────────────────────────────────────────────
_CB_FAILURE_THRESHOLD = 5        # consecutive fetch errors → open
_CB_OPEN_TTL_SECONDS  = 1800     # 30 min open window → half-open probe
_CB_HALF_OPEN_KEY     = "cb:half_open:{platform}"
_CB_FAILURE_KEY       = "cb:failures:{platform}"
_CB_OPEN_KEY          = "cb:open:{platform}"


async def _cb_is_open(platform_value: str) -> bool:
    """Return True when the circuit is OPEN (skip this platform)."""
    try:
        r = await _get_footer_redis()
        return bool(await r.exists(_CB_OPEN_KEY.format(platform=platform_value)))
    except Exception:
        return False  # fail-open: never block on Redis error


async def _cb_record_failure(platform_value: str) -> None:
    """Increment failure counter; open circuit when threshold reached."""
    try:
        r = await _get_footer_redis()
        key = _CB_FAILURE_KEY.format(platform=platform_value)
        count = await r.incr(key)
        await r.expire(key, _CB_OPEN_TTL_SECONDS)
        if count >= _CB_FAILURE_THRESHOLD:
            open_key = _CB_OPEN_KEY.format(platform=platform_value)
            await r.set(open_key, "1", ex=_CB_OPEN_TTL_SECONDS)
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"[circuit_breaker] {platform_value} OPENED after {count} failures"
            )
            # v3.2: send immediate alert to developer
            import asyncio as _asyncio
            from bot.utils.alerts import alert_critical
            _asyncio.ensure_future(alert_critical(
                "Circuit Breaker Opened",
                f"Platform <b>{platform_value}</b> tripped after {count} consecutive failures.",
                platform=platform_value,
                failures=count,
                recovery="Auto-retry in 30 min (half-open probe)",
                action="Check platform status or increase max_consecutive_errors",
            ))
    except Exception:
        pass


async def _cb_record_success(platform_value: str) -> None:
    """On success, reset failure counter and close circuit."""
    try:
        r = await _get_footer_redis()
        await r.delete(
            _CB_FAILURE_KEY.format(platform=platform_value),
            _CB_OPEN_KEY.format(platform=platform_value),
            _CB_HALF_OPEN_KEY.format(platform=platform_value),
        )
    except Exception:
        pass


class BasePlatformFetcher(ABC):
    """
    Abstract base for all platform fetchers.
    Subclasses implement only fetch_posts().
    Everything else (dedup, AI, delivery, error tracking) is handled here.
    """

    platform: Platform  # must be set by subclass

    def __init__(self):
        from bot.utils.logger import STFLogger
        self.log = STFLogger(LogModule.SYSTEM)

    # ── Must implement ───────────────────────

    @abstractmethod
    async def fetch_posts(self, account: Account) -> FetchResult:
        """
        Fetch new posts for an account.
        Return FetchResult with normalized FetchedPost objects.
        Should NOT handle deduplication — base class does that.
        """
        ...

    # ── Main pipeline ────────────────────────

    async def run(self, account_id: int) -> int:
        """
        Full fetch pipeline for one account.
        Returns number of new posts delivered.
        """
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import Account, User, PlanConfig

        async with get_session() as session:
            account = (await session.execute(
                select(Account).where(Account.id == account_id)
            )).scalar_one_or_none()

            if not account or not account.is_active:
                return 0

            user = (await session.execute(
                select(User).where(User.id == account.user_id)
            )).scalar_one_or_none()

            if not user or user.is_banned:
                return 0

        # ── Circuit Breaker ───────────────────────────────────────────────────
        platform_val = self.platform.value
        if await _cb_is_open(platform_val):
            r = await _get_footer_redis()
            half_key = _CB_HALF_OPEN_KEY.format(platform=platform_val)
            if not await r.set(half_key, "1", ex=_CB_OPEN_TTL_SECONDS, nx=True):
                return 0  # another worker already probing — skip

        # Fetch from platform
        try:
            result = await self.fetch_posts(account)
        except Exception as e:
            await self._record_error(account, str(e), exc=e)
            await _cb_record_failure(platform_val)
            return 0

        # Track for dashboard + circuit state
        # Import at module level in the function body is cached after first call,
        # but moved here as a top-of-file import would create a circular dependency
        # (base.py → tasks.py → base.py). The deferred import is the correct pattern;
        # the overhead is one dict lookup per call after first import — negligible.
        from worker.tasks import record_fetch_result  # deferred: avoids circular import
        fetch_ok = not (result.error or result.platform_down)
        await record_fetch_result(platform_val, success=fetch_ok)

        if result.error or result.platform_down:
            await self._record_error(account, result.error or "platform_down")
            await _cb_record_failure(platform_val)
            return 0

        await _cb_record_success(platform_val)

        if result.account_not_found or result.account_private:
            # Don't retry — notify user
            await self._notify_account_issue(user, account, result)
            return 0

        if not result.posts:
            await self._reset_errors(account)
            return 0

        # Deduplicate
        new_posts = await self._filter_seen(account.id, result.posts)

        if not new_posts:
            await self._reset_errors(account)
            return 0

        # Deliver posts
        delivered = 0
        for post in new_posts:
            try:
                await self._deliver_post(user, account, post)
                await self._mark_sent(account.id, post)
                delivered += 1
                # Rate limit between posts
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Delivery failed for post {post.post_id}: {e}")

        # Update account health
        await self._update_fetch_success(account)

        return delivered

    # ── Deduplication ────────────────────────

    async def _filter_seen(
        self,
        account_id: int,
        posts: list[FetchedPost],
    ) -> list[FetchedPost]:
        """Filter out posts already sent to this user."""
        from bot.database import get_session
        from sqlalchemy import select

        hashes = [p.content_hash for p in posts]

        async with get_session() as session:
            existing = (await session.execute(
                select(SentPost.post_hash)
                .where(
                    SentPost.account_id == account_id,
                    SentPost.post_hash.in_(hashes),
                )
            )).scalars().all()

        seen = set(existing)
        return [p for p in posts if p.content_hash not in seen]

    async def _mark_sent(self, account_id: int, post: FetchedPost) -> None:
        from bot.database import get_session
        async with get_session() as session:
            entry = SentPost(
                account_id=account_id,
                post_id=post.post_id[:256] if post.post_id else None,
                post_hash=post.content_hash,
                title=post.title[:512] if post.title else None,
                url=post.url[:1024] if post.url else None,
                published_at=post.published_at,
            )
            session.add(entry)

    # ── Post Delivery ─────────────────────────

    async def _deliver_post(
        self,
        user: User,
        account: Account,
        post: FetchedPost,
    ) -> None:
        """Build message and send to user (or their channel)."""

        # AI processing (premium only)
        ai_result = {}
        if user.plan.value == "premium" and any([
            user.ai_summarize, user.ai_translate,
            user.ai_categorize, user.ai_spam_tag,
        ]):
            from bot.services.ai_service import process_post
            # Detect post language so we skip translation when unnecessary
            from bot.services.ai_service import detect_language
            post_text_for_ai = post.description or post.title or ""
            detected_lang = "en"
            if user.ai_translate and post_text_for_ai:
                detected_lang = await detect_language(post_text_for_ai) or "en"

            ai_result = await process_post(
                post_text=post_text_for_ai,
                user_id=user.id,
                user_language=user.ai_translate_lang or user.language,
                post_language=detected_lang,   # now accurately detected
                do_summary=user.ai_summarize,
                do_translate=user.ai_translate,
                do_spam_check=user.ai_spam_tag,
                do_categorize=user.ai_categorize,
            )

        # Build message text
        text = await self._format_post(user, account, post, ai_result)

        # Buttons — use new video-aware builder
        from bot.handlers.video import build_post_buttons_with_video, should_preview_url
        markup = build_post_buttons_with_video(
            platform=account.platform.value,
            original_url=post.url,
            has_video=post.has_video,
            user=user,
            lang=user.language,
        )

        # Preview: enable for video platforms (streams inside Telegram)
        disable_preview = not should_preview_url(account.platform.value, post.url)

        # Target: channel or DM
        target_id = user.channel_forward_id or user.telegram_id

        from bot.utils.telegram_utils import get_bot
        from bot.utils.fixes import safe_send_fixed
        bot = get_bot()

        try:
            if post.image_url and not post.has_video:
                await bot.send_photo(
                    chat_id=target_id,
                    photo=post.image_url,
                    caption=text[:1024],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await bot.send_message(
                    chat_id=target_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=disable_preview,
                )
        except Exception as e:
            # Check if channel access lost
            error_str = str(e).lower()
            if "chat not found" in error_str or "forbidden" in error_str:
                if user.channel_forward_id:
                    await self._handle_channel_error(user)
                    # Retry to DM
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                else:
                    raise
            else:
                raise

    async def _format_post(
        self,
        user: User,
        account: Account,
        post: FetchedPost,
        ai_result: dict,
    ) -> str:
        """Format a post for Telegram HTML delivery."""
        from bot.utils.translator import t

        lang = user.language

        # Platform emoji + name
        platform_icons = {
            "youtube":   "🎬 YouTube",
            "twitter":   "🐦 Twitter/X",
            "instagram": "📸 Instagram",
            "rss":       "📡 RSS",
            "tiktok":    "🎵 TikTok",
            "linkedin":  "💼 LinkedIn",
            "reddit":    "🤖 Reddit",
            "telegram":  "✈️ Telegram",
            "bluesky":   "🦋 Bluesky",
            "mastodon":  "🐘 Mastodon",
            "threads":   "🧵 Threads",
            "facebook":  "👥 Facebook",
            "discord":   "🎮 Discord",
        }
        platform_label = platform_icons.get(account.platform.value, account.platform.value.capitalize())

        # Category name
        category_line = ""
        if account.category_id:
            # Category name resolved at call time — passed via extra or fetched
            cat_name = post.extra.get("category_name")
            if cat_name:
                category_line = f"📁 {cat_name}\n"

        # Date
        date_str = ""
        if post.published_at:
            date_str = post.published_at.strftime("%Y-%m-%d %H:%M:%S")

        # Spam tag
        spam_line = ""
        is_spam = ai_result.get("is_spam", False)
        if is_spam:
            spam_line = f"\n{t('post.spam_tag', lang)}"

        # AI category
        ai_cat_line = ""
        ai_cat = ai_result.get("category")
        if ai_cat:
            ai_cat_line = f"\n🏷 {ai_cat.capitalize()}"

        # Main content
        lines = [
            f"<b>{platform_label}</b>",
            category_line,
            f"📌 {account.display_name}",
        ]
        if date_str:
            lines.append(f"🕐 {date_str}")
        lines.append("")
        lines.append(f"<b>{post.title}</b>")

        # Description (truncated)
        if post.description and len(post.description) > 50:
            desc = post.description[:400]
            if len(post.description) > 400:
                desc += "..."
            lines.append(desc)

        # AI summary
        summary = ai_result.get("summary")
        if summary:
            lines.append(f"\n{t('post.ai_summary_label', lang)}\n{summary}")

        # AI translation
        translation = ai_result.get("translation")
        if translation:
            sep = "─" * 16
            if user.ai_show_original:
                lines.append(f"\n{sep}\n{t('post.ai_translation_label', lang)}\n{translation}")
            else:
                # Replace content with translation
                lines = [f"<b>{platform_label}</b>", f"📌 {account.display_name}"]
                if date_str:
                    lines.append(f"🕐 {date_str}")
                lines.append("")
                lines.append(translation)

        lines.append(spam_line)
        lines.append(ai_cat_line)

        # Footer (every N posts) — counter persisted in Redis so it survives restarts
        if user.footer_enabled:
            from config import config as cfg
            try:
                r = await _get_footer_redis()
                counter_key = f"footer_counter:{user.id}"
                new_count = await r.incr(counter_key)
            except Exception:
                # Redis unavailable — fall back to in-memory counter
                user.footer_post_counter = (user.footer_post_counter or 0) + 1
                new_count = user.footer_post_counter
            if new_count % cfg.rate_limit.footer_every_n_posts == 1:
                footer = t("post.footer", lang, bot_username=cfg.telegram.username)
                lines.append(f"\n{'─' * 16}\n{footer}")

        return "\n".join(l for l in lines if l is not None)

    # ── Error Tracking ───────────────────────

    async def _record_error(
        self,
        account: Account,
        message: str,
        exc: Optional[Exception] = None,
    ) -> None:
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import Account as AccModel, PlatformError

        async with get_session() as session:
            acc = (await session.execute(
                select(AccModel).where(AccModel.id == account.id)
            )).scalar_one_or_none()

            if acc:
                acc.error_count += 1
                acc.consecutive_errors += 1
                acc.last_error = message[:500]
                acc.last_error_at = datetime.now(timezone.utc)

            # Log platform error
            session.add(PlatformError(
                platform=account.platform,
                error_type=type(exc).__name__ if exc else "FetchError",
                message=message[:500],
            ))

        # Alert admin if too many consecutive errors
        from config import config
        if acc and acc.consecutive_errors >= config.platform.max_consecutive_errors:
            from bot.utils.logger import STFLogger
            from bot.models import LogModule
            log = STFLogger(LogModule.SYSTEM)
            cookie_platforms = {'twitter', 'instagram', 'tiktok', 'threads', 'facebook'}
            is_cookie = account.platform.value in cookie_platforms
            hint = ' — RSSHub cookie may have expired' if is_cookie else ''
            await log.error(
                f"Platform {account.platform.value} has {acc.consecutive_errors} "
                f"consecutive errors for account {account.display_name}{hint}",
                account_id=account.id,
                platform=account.platform,
            )
            # Notify user once when threshold is first reached
            if acc.consecutive_errors == config.platform.max_consecutive_errors:
                await self._notify_user_platform_issue(account, is_cookie)

    async def _reset_errors(self, account: Account) -> None:
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import Account as AccModel

        async with get_session() as session:
            acc = (await session.execute(
                select(AccModel).where(AccModel.id == account.id)
            )).scalar_one_or_none()
            if acc:
                acc.consecutive_errors = 0

    async def _update_fetch_success(self, account: Account) -> None:
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import Account as AccModel

        async with get_session() as session:
            acc = (await session.execute(
                select(AccModel).where(AccModel.id == account.id)
            )).scalar_one_or_none()
            if acc:
                acc.last_successful_fetch = datetime.now(timezone.utc)
                acc.consecutive_errors = 0

    async def _notify_account_issue(
        self,
        user: User,
        account: Account,
        result: FetchResult,
    ) -> None:
        from bot.utils.telegram_utils import safe_send_message
        from bot.utils.translator import t

        lang = user.language
        if result.account_private:
            msg = t("errors.private_account", lang)
        else:
            msg = t("account.not_found", lang)

        # Disable the account to stop retrying
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import Account as AccModel

        async with get_session() as session:
            acc = (await session.execute(
                select(AccModel).where(AccModel.id == account.id)
            )).scalar_one_or_none()
            if acc:
                acc.is_active = False

        await safe_send_message(
            user.telegram_id,
            f"⚠️ <b>{account.display_name}</b>\n{msg}",
            parse_mode="HTML",
        )

    async def _notify_user_platform_issue(
        self,
        account: "Account",
        is_cookie_platform: bool = False,
    ) -> None:
        """
        Notify user when their account has too many consecutive fetch failures.
        Called once when max_consecutive_errors threshold is first reached.
        No technical details exposed to the user (no mention of cookies, RSSHub).
        """
        from bot.database import get_session
        from bot.models import User as UserModel
        from bot.utils.telegram_utils import safe_send_message
        from sqlalchemy import select

        async with get_session() as session:
            user = (await session.execute(
                select(UserModel).where(UserModel.id == account.user_id)
            )).scalar_one_or_none()

        if not user:
            return

        platform_label = {
            "twitter": "Twitter / X",
            "instagram": "Instagram",
            "tiktok": "TikTok",
            "threads": "Threads",
            "facebook": "Facebook",
            "youtube": "YouTube",
            "reddit": "Reddit",
            "linkedin": "LinkedIn",
            "telegram": "Telegram",
            "discord": "Discord",
            "bluesky": "Bluesky",
            "mastodon": "Mastodon",
            "rss": "RSS",
        }.get(account.platform.value, account.platform.value.capitalize())

        name = account.display_name or account.identifier

        if is_cookie_platform:
            msg = (
                f"<b>{name}</b> ({platform_label})\n\n"
                "Fetching posts from this account is temporarily unavailable.\n"
                "We are working to restore it. Posts will resume automatically.\n\n"
                "No action needed on your side."
            )
        else:
            msg = (
                f"<b>{name}</b> ({platform_label})\n\n"
                "We could not fetch new posts from this account for a while.\n"
                "We will keep retrying automatically."
            )

        try:
            await safe_send_message(user.telegram_id, msg, parse_mode="HTML")
            logger.info(
                f"Notified user {user.telegram_id} about platform issue: "
                f"{account.platform.value}/@{account.identifier}"
            )
        except Exception as e:
            logger.warning(f"Could not notify user about platform issue: {e}")

    async def _handle_channel_error(self, user: "User") -> None:
        """Disable channel forward after repeated permission errors."""
        from bot.database import get_session
        from sqlalchemy import select
        from bot.models import User as UserModel
        from bot.utils.telegram_utils import safe_send_message
        from bot.utils.translator import t

        async with get_session() as session:
            db_user = (await session.execute(
                select(UserModel).where(UserModel.id == user.id)
            )).scalar_one_or_none()
            if db_user:
                db_user.channel_forward_errors += 1
                from config import config
                if db_user.channel_forward_errors >= config.app.channel_forward_max_errors:
                    db_user.channel_forward_id = None
                    db_user.channel_forward_errors = 0
                    user.channel_forward_id = None

                    await safe_send_message(
                        user.telegram_id,
                        t("errors.channel_permission", user.language),
                    )
