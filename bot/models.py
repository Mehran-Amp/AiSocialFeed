"""
SocialtoFeed — Database Models
Complete schema for all tables.
Uses SQLAlchemy async ORM.
"""

from __future__ import annotations

import enum
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum as SAEnum,
    Float, ForeignKey, Index, Integer, JSON, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
#  Enums
# ─────────────────────────────────────────────

class PlanType(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"


class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    RSS = "rss"
    TIKTOK = "tiktok"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    BLUESKY = "bluesky"
    MASTODON = "mastodon"
    THREADS = "threads"
    FACEBOOK = "facebook"
    DISCORD = "discord"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TransactionMethod(str, enum.Enum):
    CRYPTO = "crypto"  # CoinEx auto-verified
    MASTERCARD = "mastercard"


class SubscriptionPeriod(str, enum.Enum):
    MONTHLY = "monthly"
    BIANNUAL = "biannual"
    YEARLY = "yearly"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"


class TicketSubject(str, enum.Enum):
    TECHNICAL = "technical"
    PAYMENT = "payment"
    GENERAL = "general"
    REPORT = "report"


class LogLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogModule(str, enum.Enum):
    BOT = "bot"
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    RSS = "rss"
    TIKTOK = "tiktok"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    TELEGRAM_CH = "telegram_ch"
    AI = "ai"
    PAYMENT = "payment"
    DOWNLOAD = "download"
    WORKER = "worker"
    ADMIN = "admin"
    SYSTEM = "system"


# ─────────────────────────────────────────────
#  Base
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Adds created_at and updated_at to any model."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


# ─────────────────────────────────────────────
#  Plan Configuration (editable from admin)
# ─────────────────────────────────────────────

class PlanConfig(Base, TimestampMixin):
    """
    Stores per-plan limits and prices.
    Admin can change any value without code changes.
    Cached in Redis for 1 hour.
    """
    __tablename__ = "plan_configs"

    id = Column(Integer, primary_key=True)
    plan = Column(SAEnum(PlanType), unique=True, nullable=False)

    # Limits
    max_accounts = Column(Integer, nullable=False, default=5)
    max_categories = Column(Integer, nullable=False, default=5)
    max_open_tickets = Column(Integer, nullable=False, default=0)
    ai_enabled = Column(Boolean, default=False, nullable=False)
    video_download = Column(Boolean, default=False, nullable=False)
    digest_enabled = Column(Boolean, default=False, nullable=False)
    channel_forward = Column(Boolean, default=False, nullable=False)
    export_csv = Column(Boolean, default=False, nullable=False)
    export_json = Column(Boolean, default=False, nullable=False)
    stats_enabled = Column(Boolean, default=False, nullable=False)
    pause_enabled = Column(Boolean, default=False, nullable=False)
    custom_interval = Column(Boolean, default=False, nullable=False)
    # AI daily limit
    ai_daily_limit = Column(Integer, default=0, nullable=False)

    # Platform access
    # Free: youtube, rss, reddit
    # Pro: + twitter, instagram, linkedin, telegram
    # Premium: + tiktok, threads, bluesky, mastodon
    platforms_json = Column(JSON, default=list)   # list of allowed platform values

    # Prices (USDT)
    price_monthly = Column(Float, nullable=False, default=0.0)
    price_biannual = Column(Float, nullable=False, default=0.0)
    price_yearly = Column(Float, nullable=False, default=0.0)

    # Full feature set as JSON — admin can override individual values
    # Keys match DEFAULT_PLAN_FEATURES in settings.py
    features_json = Column(JSON, nullable=True)   # None = use DEFAULT_PLAN_FEATURES fallback

    # Extra limit fields (readable directly without parsing JSON)
    bookmark_limit = Column(Integer, default=0, nullable=False)  # v3.3: 0 = unlimited for all plans
    ticket_limit = Column(Integer, default=1, nullable=False)
    fetch_on_demand = Column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<PlanConfig {self.plan.value}>"


# ─────────────────────────────────────────────
#  Users
# ─────────────────────────────────────────────

class User(Base, TimestampMixin):
    """Core user table."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)

    # Plan & subscription
    plan = Column(SAEnum(PlanType), default=PlanType.FREE, nullable=False)
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    subscription_paused_at = Column(DateTime(timezone=True), nullable=True)
    subscription_pause_used = Column(Boolean, default=False, nullable=False)

    # Language & UI
    language = Column(String(10), default="en", nullable=False)

    # AI preferences (premium only)
    ai_summarize = Column(Boolean, default=False)
    ai_translate = Column(Boolean, default=False)
    ai_translate_lang = Column(String(10), nullable=True)   # target language code
    ai_show_original = Column(Boolean, default=True)        # show original alongside translation
    ai_categorize = Column(Boolean, default=False)
    ai_spam_tag = Column(Boolean, default=False)            # tag (not block) spam posts

    # Digest (premium only)
    digest_enabled = Column(Boolean, default=False)
    digest_interval_hours = Column(Integer, default=24)
    digest_next_send = Column(DateTime(timezone=True), nullable=True)

    # Channel forward (premium only)
    channel_forward_id = Column(BigInteger, nullable=True)
    channel_forward_errors = Column(SmallInteger, default=0)

    # Footer
    footer_enabled = Column(Boolean, default=True)
    footer_post_counter = Column(Integer, default=0)  # tracks every-N-posts

    # Referral
    referral_code = Column(String(16), unique=True, nullable=False,
                           default=lambda: secrets.token_urlsafe(10))
    referred_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    referral_bonus_accounts      = Column(Integer, default=0)
    referral_count               = Column(Integer, default=0, nullable=False)
    referral_points              = Column(Integer, default=0, nullable=False)
    referral_milestones_claimed  = Column(Integer, default=0, nullable=False)  # v4.2: highest 5-friend tier paid

    # Rate limiting & AI usage
    daily_ai_count = Column(Integer, default=0)
    last_ai_reset = Column(DateTime(timezone=True), nullable=True)
    daily_request_count = Column(Integer, default=0)
    last_request_reset = Column(DateTime(timezone=True), nullable=True)

    # Expiry warnings
    last_expiry_warning_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(String(256), nullable=True)

    # Bookmark settings
    bookmark_count = Column(Integer, default=0)   # cached count

    # Misc
    # Spam filter (Premium)
    hide_spam_posts = Column(Boolean, default=False)
    # Email digest (Premium)
    email = Column(String(256), nullable=True)
    email_digest_enabled = Column(Boolean, default=False)
    email_unsubscribe_token = Column(String(64), nullable=True)
    # Share bot tracking (3 times first 3 weeks)
    share_prompt_count = Column(Integer, default=0)
    share_prompt_last_at = Column(DateTime(timezone=True), nullable=True)
    # Admin credit
    credit_expires_at = Column(DateTime(timezone=True), nullable=True)
    credit_plan = Column(SAEnum(PlanType), nullable=True)
    credit_granted_by = Column(String(64), nullable=True)
    # Grace period 48h after expiry
    grace_until                  = Column(DateTime(timezone=True), nullable=True)
    last_feed_viewed_at          = Column(DateTime(timezone=True), nullable=True)  # v4.2 Hybrid Updates
    fetch_interval_minutes       = Column(Integer, default=30, nullable=False)  # v4.2.1: Premium 10/30/60
    menu_hidden                  = Column(Boolean, default=False, nullable=False)  # v4.2.1: hide/unhide main menu
    original_plan_before_grace = Column(SAEnum(PlanType), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    accounts = relationship("Account", back_populates="user", lazy="select")
    categories = relationship("Category", back_populates="user", lazy="select")
    transactions = relationship("Transaction", back_populates="user", lazy="select")
    tickets = relationship("SupportTicket", back_populates="user", lazy="select")
    referred_by = relationship("User", remote_side="User.id", foreign_keys=[referred_by_id])

    def effective_max_accounts(self, plan_base_limit: int) -> int:
        """Returns base plan limit + referral bonus accounts."""
        return plan_base_limit + (self.referral_bonus_accounts or 0)

    def __repr__(self):
        return f"<User tg:{self.telegram_id} plan:{self.plan.value}>"


# ─────────────────────────────────────────────
#  Categories
# ─────────────────────────────────────────────

class Category(Base, TimestampMixin):
    """User-defined account groups."""
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_category_name"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(64), nullable=False)
    emoji = Column(String(8), nullable=True)     # optional custom emoji
    is_default = Column(Boolean, default=False)  # "General" category, undeletable
    sort_order = Column(SmallInteger, default=0)

    user = relationship("User", back_populates="categories")
    accounts = relationship("Account", back_populates="category", lazy="select")


# ─────────────────────────────────────────────
#  Accounts (monitored social accounts)
# ─────────────────────────────────────────────

class Account(Base, TimestampMixin):
    """A social media account being monitored for a user."""
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "identifier", name="uq_user_platform_account"),
        Index("ix_accounts_next_fetch", "next_fetch_at", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)

    platform = Column(SAEnum(Platform), nullable=False)
    identifier = Column(String(256), nullable=False)   # channel ID, username, RSS URL
    display_name = Column(String(256), nullable=True)  # human-readable name
    feed_url = Column(String(512), nullable=True)      # resolved RSS/feed URL

    is_active = Column(Boolean, default=True, nullable=False)

    # Fetch scheduling
    custom_interval_minutes = Column(Integer, nullable=True)  # NULL = use global default
    next_fetch_at = Column(DateTime(timezone=True), nullable=True)
    last_successful_fetch = Column(DateTime(timezone=True), nullable=True)
    is_initial_fetch = Column(Boolean, default=True, nullable=False)

    # Health tracking
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_errors = Column(SmallInteger, default=0)

    # Relationships
    user = relationship("User", back_populates="accounts")
    category = relationship("Category", back_populates="accounts")
    sent_posts = relationship("SentPost", back_populates="account", lazy="dynamic")

    def __repr__(self):
        return f"<Account {self.platform.value}:{self.identifier}>"


# ─────────────────────────────────────────────
#  Sent Posts (deduplication + archive)
# ─────────────────────────────────────────────

class SentPost(Base):
    """
    Tracks every post sent to a user.
    Used for: deduplication, archive, stats.
    Partitioned conceptually by created_at — cleanup job deletes records > 90 days.
    """
    __tablename__ = "sent_posts"
    __table_args__ = (
        UniqueConstraint("account_id", "post_hash", name="uq_account_post"),
        Index("ix_sent_posts_account_sent", "account_id", "sent_at"),
        Index("ix_sent_posts_cleanup", "sent_at"),  # for bulk delete by date
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)

    # Post identification
    post_id = Column(String(256), nullable=True)    # platform's own ID
    post_hash = Column(String(64), nullable=False)  # SHA-256 of URL or content
    title = Column(String(512), nullable=True)
    url = Column(String(1024), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    account = relationship("Account", back_populates="sent_posts")

    @staticmethod
    def make_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()


# ─────────────────────────────────────────────
#  Bookmarks
# ─────────────────────────────────────────────

class Bookmark(Base):
    """
    User-saved posts for later reading.
    Limits: Free=10, Pro=50, Premium=unlimited(500)
    """
    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "post_hash", name="uq_user_bookmark"),
        Index("ix_bookmarks_user", "user_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform = Column(SAEnum(Platform), nullable=False)
    account_name = Column(String(256), nullable=True)
    title = Column(String(512), nullable=True)
    url = Column(String(1024), nullable=False)
    post_hash = Column(String(64), nullable=False)
    thumbnail_url = Column(String(1024), nullable=True)
    has_video = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    @staticmethod
    def make_hash(url: str) -> str:
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()


# ─────────────────────────────────────────────
#  USDT Addresses
# ─────────────────────────────────────────────

class USDTAddress(Base, TimestampMixin):
    """Admin-managed USDT payment addresses (max 3)."""
    __tablename__ = "usdt_addresses"

    id = Column(Integer, primary_key=True)
    label = Column(String(64), nullable=False)      # e.g. "Main Address"
    address = Column(String(128), nullable=False)
    network = Column(String(32), default="TRC20", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)


# ─────────────────────────────────────────────
#  Transactions
# ─────────────────────────────────────────────

class Transaction(Base, TimestampMixin):
    """Purchase requests submitted by users."""
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("txid", name="uq_txid"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    plan = Column(SAEnum(PlanType), nullable=False)
    period = Column(SAEnum(SubscriptionPeriod), nullable=False)
    amount_usdt = Column(Float, nullable=False)
    payment_method = Column(SAEnum(TransactionMethod), default=TransactionMethod.CRYPTO)
    status = Column(SAEnum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)

    # Proof
    txid = Column(String(128), nullable=True)       # TRC20 transaction ID
    screenshot_path = Column(String(512), nullable=True)
    usdt_address_id = Column(Integer, ForeignKey("usdt_addresses.id"), nullable=True)

    # Admin action
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(64), nullable=True)  # admin username
    reject_reason = Column(String(256), nullable=True)

    # Tronscan validation result
    tronscan_verified = Column(Boolean, nullable=True)
    tronscan_data = Column(JSON, nullable=True)

    # CoinEx auto-payment fields
    deposit_address = Column(String(128), nullable=True)      # generated wallet address
    network = Column(String(16), nullable=True)               # TRC20 / BEP20 / ERC20
    address_expires_at = Column(DateTime(timezone=True), nullable=True)
    address_generated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="transactions")
    usdt_address = relationship("USDTAddress")

    def __repr__(self):
        return f"<Transaction #{self.id} {self.status.value}>"


# ─────────────────────────────────────────────
#  System Config (key-value store)
# ─────────────────────────────────────────────

class SystemConfig(Base, TimestampMixin):
    """
    Key-value store for admin-configurable settings.
    Sensitive values (API keys) stored encrypted.
    """
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    is_encrypted = Column(Boolean, default=False)
    description = Column(String(256), nullable=True)
    updated_by = Column(String(64), nullable=True)

    # Common keys (used as constants elsewhere):
    # "deepseek_api_key"        — encrypted
    # "bot_token"               — encrypted
    # "welcome_message"
    # "maintenance_mode"
    # "nowpayments_enabled"
    # "nowpayments_api_key"     — encrypted


# ─────────────────────────────────────────────
#  Support Tickets
# ─────────────────────────────────────────────

class SupportTicket(Base, TimestampMixin):
    """Support tickets — pro and premium only."""
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(16), unique=True, nullable=False,
                           default=lambda: f"TKT-{secrets.token_hex(4).upper()}")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject = Column(SAEnum(TicketSubject), nullable=False)
    status = Column(SAEnum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket",
                            cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<Ticket {self.ticket_number} [{self.status.value}]>"


class TicketMessage(Base):
    """Individual messages within a support ticket."""
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False)
    sender_type = Column(String(10), nullable=False)  # "user" or "admin"
    message = Column(Text, nullable=True)
    attachments = Column(JSON, default=list)  # list of file paths
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    ticket = relationship("SupportTicket", back_populates="messages")


# ─────────────────────────────────────────────
#  System Logs
# ─────────────────────────────────────────────

class SystemLog(Base):
    """
    Structured log entries stored in DB.
    Viewable and filterable from admin panel.
    Exportable as JSON for debugging.
    Auto-cleaned after LOG_RETENTION_DAYS.
    """
    __tablename__ = "system_logs"
    __table_args__ = (
        Index("ix_system_logs_level_created", "level", "created_at"),
        Index("ix_system_logs_module_created", "module", "created_at"),
        Index("ix_system_logs_cleanup", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    level = Column(SAEnum(LogLevel), nullable=False, index=True)
    module = Column(SAEnum(LogModule), nullable=False)
    message = Column(Text, nullable=False)

    # Structured context
    user_id = Column(Integer, nullable=True)          # related user (if any)
    account_id = Column(Integer, nullable=True)       # related account (if any)
    platform = Column(SAEnum(Platform), nullable=True)

    # Full debug info
    details = Column(JSON, nullable=True)             # stack trace, request data, etc.
    extra = Column(JSON, nullable=True)               # any additional k/v pairs

    # Admin workflow
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_note = Column(String(512), nullable=True)

    # Alert tracking (avoid duplicate alerts)
    alert_sent = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def to_debug_dict(self) -> dict:
        """Serializes this log entry for debug report export."""
        return {
            "id": self.id,
            "time": self.created_at.isoformat() if self.created_at else None,
            "level": self.level.value,
            "module": self.module.value,
            "message": self.message,
            "user_id": self.user_id,
            "account_id": self.account_id,
            "platform": self.platform.value if self.platform else None,
            "details": self.details,
            "extra": self.extra,
            "resolved": self.resolved,
        }


# ─────────────────────────────────────────────
#  Platform Errors (aggregated)
# ─────────────────────────────────────────────

class PlatformError(Base):
    """
    Aggregated error tracking per platform.
    Used for admin dashboard health status.
    """
    __tablename__ = "platform_errors"

    id = Column(Integer, primary_key=True)
    platform = Column(SAEnum(Platform), nullable=False)
    error_type = Column(String(64), nullable=False)   # ConnectionError, RateLimitError, etc.
    message = Column(Text, nullable=True)
    affected_accounts = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ─────────────────────────────────────────────
#  Daily Stats
# ─────────────────────────────────────────────

class DailyStat(Base):
    """Aggregated daily statistics per platform."""
    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("date", "platform", name="uq_daily_stat"),
    )

    id = Column(Integer, primary_key=True)
    date = Column(String(10), nullable=False)          # "YYYY-MM-DD"
    platform = Column(SAEnum(Platform), nullable=True) # NULL = total across all
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    total_posts_sent = Column(Integer, default=0)
    new_users = Column(Integer, default=0)
    new_accounts = Column(Integer, default=0)
    ai_calls = Column(Integer, default=0)
    downloads = Column(Integer, default=0)


# ─────────────────────────────────────────────
#  Rate Limit Queue
# ─────────────────────────────────────────────

class RateLimitEntry(Base):
    """Tracks per-user actions for rate limiting."""
    __tablename__ = "rate_limit_queue"
    __table_args__ = (
        Index("ix_rate_limit_user_action", "user_id", "action", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    action = Column(String(64), nullable=False)  # "referral", "fetch", "download"
    ip_hash = Column(String(64), nullable=True)  # hashed IP for referral abuse check
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ─────────────────────────────────────────────
#  Admin Credit Log
# ─────────────────────────────────────────────

class AdminCreditLog(Base):
    """Admin-granted free subscription credits — no payment required."""
    __tablename__ = "admin_credit_logs"
    __table_args__ = (Index("ix_credit_logs_user", "user_id", "granted_at"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan = Column(SAEnum(PlanType), nullable=False)
    days = Column(Integer, nullable=False)
    reason = Column(String(256), nullable=True)
    granted_by = Column(String(64), nullable=False)
    granted_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
