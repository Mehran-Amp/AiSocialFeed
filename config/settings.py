"""
SocialtoFeed — Central Configuration
All settings loaded from environment variables with safe defaults.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return value


def _list_env(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ─────────────────────────────────────────────
#  Telegram
# ─────────────────────────────────────────────
@dataclass
class TelegramConfig:
    token: str = field(default_factory=lambda: _require("BOT_TOKEN"))
    admin_id: int = field(default_factory=lambda: int(_require("ADMIN_TELEGRAM_ID")))
    username: str = field(default_factory=lambda: os.getenv("BOT_USERNAME", "AiSocialFeedBot"))
    webhook_url: Optional[str] = field(default_factory=lambda: os.getenv("WEBHOOK_URL"))
    session_timeout: int = 1800
    # Optional: Telegram Instant View rhash.
    # Generate at https://instantview.telegram.org — leave empty to disable IV buttons.
    iv_rhash: Optional[str] = field(default_factory=lambda: os.getenv("TELEGRAM_IV_RHASH") or None)


# ─────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────
@dataclass
class DatabaseConfig:
    url: str = field(default_factory=lambda: _require("DATABASE_URL"))
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800


# ─────────────────────────────────────────────
#  Redis & Celery
# ─────────────────────────────────────────────
@dataclass
class RedisConfig:
    url: str = field(default_factory=lambda: _require("REDIS_URL"))
    celery_broker: str = field(default_factory=lambda: _require("CELERY_BROKER_URL"))
    celery_backend: str = field(default_factory=lambda: _require("CELERY_RESULT_BACKEND"))
    plan_config_ttl: int = 3600
    user_ttl: int = 300
    platform_status_ttl: int = 900
    rsshub_health_ttl: int = 900


# ─────────────────────────────────────────────
#  DeepSeek AI
# ─────────────────────────────────────────────
@dataclass
class DeepSeekConfig:
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY"))
    model_fast: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL_FAST", "deepseek-chat"))
    model_pro: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL_PRO", "deepseek-chat"))
    base_url: str = "https://api.deepseek.com"
    timeout: int = 30
    max_retries: int = 3
    daily_limit_per_user: int = 500
    max_tokens_summary: int = 500
    max_tokens_translate: int = 1000
    max_tokens_qa: int = 800

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


# ─────────────────────────────────────────────
#  RSSHub — self-hosted, with cookie support
# ─────────────────────────────────────────────
@dataclass
class RSSHubConfig:
    url: str = field(
        default_factory=lambda: os.getenv("RSSHUB_URL", "http://rsshub:1200")
    )
    cookie_twitter: str = field(
        default_factory=lambda: os.getenv("RSSHUB_COOKIE_TWITTER", "")
    )
    cookie_instagram: str = field(
        default_factory=lambda: os.getenv("RSSHUB_COOKIE_INSTAGRAM", "")
    )
    cookie_tiktok: str = field(
        default_factory=lambda: os.getenv("RSSHUB_COOKIE_TIKTOK", "")
    )


# ─────────────────────────────────────────────
#  Platform Sources
# ─────────────────────────────────────────────
@dataclass
class PlatformConfig:
    # Kept for LinkedIn fallback if needed
    rssbridge_instances: list[str] = field(
        default_factory=lambda: _list_env(
            "RSSBRIDGE_INSTANCES",
            "https://rss-bridge.org/bridge01,https://rssbridge.flossboxin.org.in"
        )
    )
    default_fetch_interval: int = 30
    min_fetch_interval: int = 5
    telegram_channel_interval: int = 5
    platform_health_check_interval: int = 15
    max_consecutive_errors: int = 5


# ─────────────────────────────────────────────
#  Download (yt-dlp)
# ─────────────────────────────────────────────
@dataclass
class DownloadConfig:
    max_concurrent: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
    )
    timeout: int = field(
        default_factory=lambda: int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "300"))
    )
    max_filesize_mb: int = 50
    output_dir: str = "/app/media/downloads"
    quality_360p_always_download: bool = True
    quality_720p_max_mb: int = 50


# ─────────────────────────────────────────────
#  Payment
# ─────────────────────────────────────────────
@dataclass
class PaymentConfig:
    """CoinEx crypto payment — exchange name never shown to users."""
    coinex_access_id: str = field(default_factory=lambda: os.getenv("COINEX_ACCESS_ID", ""))
    coinex_secret_key: str = field(default_factory=lambda: os.getenv("COINEX_SECRET_KEY", ""))
    address_expiry_hours: int = field(default_factory=lambda: int(os.getenv("PAYMENT_ADDRESS_EXPIRY_HOURS", "6")))
    poll_interval: int = field(default_factory=lambda: int(os.getenv("PAYMENT_POLL_INTERVAL", "90")))
    overpay_tolerance: float = field(default_factory=lambda: float(os.getenv("PAYMENT_OVERPAY_TOLERANCE", "0.01")))
    confirm_blocks: int = field(default_factory=lambda: int(os.getenv("PAYMENT_CONFIRM_BLOCKS", "1")))
    # NOWPayments (Mastercard) — disabled by default, keep config for future
    nowpayments_enabled: bool = field(
        default_factory=lambda: os.getenv("NOWPAYMENTS_ENABLED", "False") == "True"
    )
    nowpayments_api_key: str = field(
        default_factory=lambda: os.getenv("NOWPAYMENTS_API_KEY", "")
    )
    # Tronscan API for manual TxID verification
    tronscan_api_url: str = field(
        default_factory=lambda: os.getenv(
            "TRONSCAN_API_URL", "https://apilist.tronscanapi.com/api"
        )
    )

    NETWORKS = {
        "TRC20": {"label": "TRC20 (TRON)", "min_confirm": 1,  "fast": True},
        "BEP20": {"label": "BEP20 (BSC)",  "min_confirm": 15, "fast": False},
        "ERC20": {"label": "ERC20 (ETH)",  "min_confirm": 12, "fast": False},
    }

    @property
    def is_configured(self) -> bool:
        return bool(self.coinex_access_id and self.coinex_secret_key)


# ─────────────────────────────────────────────
#  Email (SMTP for digest)
# ─────────────────────────────────────────────
@dataclass
class EmailConfig:
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", "noreply@AiSocialFeed.com"))

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)


# ─────────────────────────────────────────────
#  Rate Limiting
# ─────────────────────────────────────────────
@dataclass
class RateLimitConfig:
    send_interval_seconds: float = 1.0
    max_concurrent_per_user: int = 5
    referral_same_ip_window: int = 3600
    expiry_warn_days: list[int] = field(default_factory=lambda: [7, 3, 1])
    footer_every_n_posts: int = 5


# ─────────────────────────────────────────────
#  Security
# ─────────────────────────────────────────────
@dataclass
class SecurityConfig:
    encryption_key: str = field(default_factory=lambda: _require("ENCRYPTION_KEY"))
    allowed_ticket_extensions: list[str] = field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".pdf"]
    )
    max_ticket_file_size_mb: int = 3


# ─────────────────────────────────────────────
#  Logging & Debug
# ─────────────────────────────────────────────
@dataclass
class LoggingConfig:
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_dir: str = "/app/logs"
    log_file: str = "/app/logs/aisocialfeed.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5
    db_log_retention_days: int = 30
    alert_on_levels: list[str] = field(default_factory=lambda: ["ERROR", "CRITICAL"])
    alert_cooldown_seconds: int = 300


# ─────────────────────────────────────────────
#  App General
# ─────────────────────────────────────────────
@dataclass
@dataclass
class AdminConfig:
    """v3.2: Developer alert routing and health check settings."""
    # Admin channel for operational digests (create a private channel, add bot as admin)
    admin_channel_id: int = field(
        default_factory=lambda: int(os.getenv("ADMIN_CHANNEL_ID", "0"))
    )
    # Suppress the same alert type for this many seconds (prevents spam)
    alert_rate_limit_seconds: int = field(
        default_factory=lambda: int(os.getenv("ALERT_RATE_LIMIT_SECONDS", "300"))
    )
    # Digest interval in hours — sent to admin channel
    digest_interval_hours: int = field(
        default_factory=lambda: int(os.getenv("DIGEST_INTERVAL_HOURS", "6"))
    )
    # Celery heartbeat TTL in seconds — worker writes this on startup
    worker_heartbeat_ttl: int = field(
        default_factory=lambda: int(os.getenv("WORKER_HEARTBEAT_TTL", "660"))
    )

    @property
    def channel_configured(self) -> bool:
        return self.admin_channel_id != 0


class AppConfig:
    default_language: str = field(
        default_factory=lambda: os.getenv("DEFAULT_LANGUAGE", "en")
    )
    translations_dir: str = "/app/translations"
    media_dir: str = "/app/media"
    dedup_window_days: int = 90
    digest_default_hour: int = 8
    max_pause_days: int = 7
    system_msg_delete_after: int = 5
    channel_forward_max_errors: int = 3


# ─────────────────────────────────────────────
#  Global Config Instance
# ─────────────────────────────────────────────
class Config:
    """Central config object. Import this everywhere."""

    def __init__(self):
        self.telegram = TelegramConfig()
        self.db = DatabaseConfig()
        self.redis = RedisConfig()
        self.deepseek = DeepSeekConfig()
        self.platform = PlatformConfig()
        self.download = DownloadConfig()
        self.payment = PaymentConfig()
        self.rate_limit = RateLimitConfig()
        self.security = SecurityConfig()
        self.logging = LoggingConfig()
        self.app = AppConfig()
        self.rsshub = RSSHubConfig()
        self.email = EmailConfig()
        self.admin = AdminConfig()  # v3.2: developer alert routing

    def validate(self) -> list[str]:
        warnings = []
        if not self.deepseek.is_configured:
            warnings.append("DEEPSEEK_API_KEY not set — AI features disabled.")
        if not self.payment.nowpayments_enabled:
            warnings.append("NOWPayments disabled — Mastercard payments not available.")
        if not self.telegram.webhook_url:
            warnings.append("WEBHOOK_URL not set — running in polling mode.")
        if not self.rsshub.url:
            warnings.append("RSSHUB_URL not set — Twitter/Instagram/TikTok/Threads feeds will fail.")
        return warnings


config = Config()


# ─────────────────────────────────────────────
#  Default Plan Features — verified vs aisocialfeed.com
# ─────────────────────────────────────────────

DEFAULT_PLAN_FEATURES = {
    "free": {
        "platforms": ["youtube", "twitter", "rss", "reddit", "telegram"],
        "max_accounts": 5, "price_monthly": 0.0, "price_yearly": 0.0,
        "stream_video": True,
        "download_link": False, "download_link_qualities": [],
        "download_file": False, "download_file_quality": None,
        "audio_link": False, "audio_file": False,
        "ai_summary": False, "ai_translate": False,
        "ai_categorize": False, "ai_spam": False, "ai_daily_limit": 0,
        "bookmark_limit": 10, "ticket_limit": 1,
        "fetch_on_demand": False, "fetch_on_demand_per_hour": 0,
        "fetch_interval_options": [60], "channel_forward": False,
        "daily_digest": False, "email_digest": False,
        "export_csv": False, "export_json": False,
        "upsell_every_n_posts": 50, "early_access": False, "priority_support": False,
    },
    "pro": {
        "platforms": ["youtube", "twitter", "instagram", "rss", "linkedin",
                      "reddit", "telegram", "threads", "bluesky", "mastodon"],
        "max_accounts": 40,
        "price_monthly": 6.0, "price_biannual": 28.8, "price_yearly": 57.6,
        "stream_video": True,
        "download_link": True, "download_link_qualities": ["480p", "720p"],
        "download_file": False, "download_file_quality": None,
        "audio_link": True, "audio_file": False,
        "ai_summary": False, "ai_translate": False,
        "ai_categorize": False, "ai_spam": False, "ai_daily_limit": 0,
        "bookmark_limit": 100, "ticket_limit": 2,
        "fetch_on_demand": False, "fetch_on_demand_per_hour": 0,
        "fetch_interval_options": [30], "channel_forward": True,
        "daily_digest": False, "email_digest": False,
        "export_csv": True, "export_json": False,
        "upsell_every_n_posts": 200, "early_access": False, "priority_support": False,
    },
    "premium": {
        "platforms": ["youtube", "twitter", "instagram", "rss", "tiktok", "linkedin",
                      "reddit", "telegram", "threads", "bluesky", "mastodon", "facebook", "discord"],
        "max_accounts": 100,
        "price_monthly": 10.0, "price_biannual": 48.0, "price_yearly": 96.0,
        "stream_video": True,
        "download_link": True, "download_link_qualities": ["480p", "720p", "1080p"],
        "download_file": True, "download_file_quality": "480p",
        "audio_link": True, "audio_file": True,
        "ai_summary": True, "ai_translate": True,
        "ai_categorize": True, "ai_spam": True, "ai_daily_limit": 0,
        "bookmark_limit": 500, "ticket_limit": 3,
        "fetch_on_demand": True, "fetch_on_demand_per_hour": 1,
        "fetch_interval_options": [5, 15, 30, 60], "channel_forward": True,
        "daily_digest": True, "email_digest": True,
        "export_csv": True, "export_json": True,
        "upsell_every_n_posts": 0, "early_access": True, "priority_support": True,
    },
}
