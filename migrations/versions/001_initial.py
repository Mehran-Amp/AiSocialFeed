"""Initial schema

Revision ID: 001_initial
Create Date: 2025-01-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_core_tables()
    _create_payment_tables()
    _create_system_tables()
    _create_support_tables()
    _add_missing_columns()


def _create_core_tables() -> None:
    # plan_configs
    op.create_table(
        "plan_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan", sa.String(16), unique=True, nullable=False),
        sa.Column("max_accounts", sa.Integer, nullable=False, default=5),
        sa.Column("max_categories", sa.Integer, nullable=False, default=5),
        sa.Column("max_open_tickets", sa.Integer, nullable=False, default=0),
        sa.Column("ai_enabled", sa.Boolean, default=False),
        sa.Column("video_download", sa.Boolean, default=False),
        sa.Column("digest_enabled", sa.Boolean, default=False),
        sa.Column("channel_forward", sa.Boolean, default=False),
        sa.Column("export_csv", sa.Boolean, default=False),
        sa.Column("export_json", sa.Boolean, default=False),
        sa.Column("stats_enabled", sa.Boolean, default=False),
        sa.Column("pause_enabled", sa.Boolean, default=False),
        sa.Column("custom_interval", sa.Boolean, default=False),
        sa.Column("ai_daily_limit", sa.Integer, default=0),
        sa.Column("price_monthly", sa.Float, nullable=False, default=0.0),
        sa.Column("price_biannual", sa.Float, nullable=False, default=0.0),
        sa.Column("price_yearly", sa.Float, nullable=False, default=0.0),
        sa.Column("features_json", postgresql.JSON),
        sa.Column("bookmark_limit", sa.Integer, default=10),
        sa.Column("ticket_limit", sa.Integer, default=1),
        sa.Column("fetch_on_demand", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("plan", sa.String(16), default="free"),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True)),
        sa.Column("subscription_paused_at", sa.DateTime(timezone=True)),
        sa.Column("subscription_pause_used", sa.Boolean, default=False),
        sa.Column("language", sa.String(10), default="en"),
        sa.Column("referral_code", sa.String(16), unique=True, nullable=False),
        sa.Column("referred_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("referral_bonus_accounts", sa.Integer, default=0),
        sa.Column("ai_summarize", sa.Boolean, default=False),
        sa.Column("ai_translate", sa.Boolean, default=False),
        sa.Column("ai_translate_lang", sa.String(10)),
        sa.Column("ai_show_original", sa.Boolean, default=True),
        sa.Column("ai_categorize", sa.Boolean, default=False),
        sa.Column("ai_spam_tag", sa.Boolean, default=False),
        sa.Column("daily_ai_count", sa.Integer, default=0),
        sa.Column("last_ai_reset", sa.DateTime(timezone=True)),
        sa.Column("digest_enabled", sa.Boolean, default=False),
        sa.Column("digest_interval_hours", sa.Integer, default=24),
        sa.Column("digest_next_send", sa.DateTime(timezone=True)),
        sa.Column("channel_forward_id", sa.BigInteger),
        sa.Column("channel_forward_errors", sa.SmallInteger, default=0),
        sa.Column("footer_enabled", sa.Boolean, default=True),
        sa.Column("footer_post_counter", sa.Integer, default=0),
        sa.Column("is_banned", sa.Boolean, default=False),
        sa.Column("ban_reason", sa.String(256)),
        sa.Column("last_expiry_warning_at", sa.DateTime(timezone=True)),
        sa.Column("last_active_at", sa.DateTime(timezone=True)),
        sa.Column("daily_request_count", sa.Integer, default=0),
        sa.Column("last_request_reset", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSON, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    # categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("emoji", sa.String(8)),
        sa.Column("is_default", sa.Boolean, default=False),
        sa.Column("sort_order", sa.SmallInteger, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_user_category_name"),
    )

    # accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("identifier", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256)),
        sa.Column("feed_url", sa.String(512)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("custom_interval_minutes", sa.Integer),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_fetch", sa.DateTime(timezone=True)),
        sa.Column("error_count", sa.Integer, default=0),
        sa.Column("last_error", sa.Text),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_errors", sa.SmallInteger, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "platform", "identifier", name="uq_user_platform_account"),
    )
    op.create_index("ix_accounts_next_fetch", "accounts", ["next_fetch_at", "is_active"])

    # sent_posts
    op.create_table(
        "sent_posts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.String(256)),
        sa.Column("post_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("url", sa.String(1024)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "post_hash", name="uq_account_post"),
    )
    op.create_index("ix_sent_posts_account_sent", "sent_posts", ["account_id", "sent_at"])
    op.create_index("ix_sent_posts_cleanup", "sent_posts", ["sent_at"])

def _create_payment_tables() -> None:
    # admin_credit_logs
    op.create_table(
        "admin_credit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("days", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("granted_by", sa.String(64), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_logs_user", "admin_credit_logs", ["user_id", "granted_at"])

    # usdt_addresses
    op.create_table(
        "usdt_addresses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("network", sa.String(32), default="TRC20"),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("is_default", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # transactions
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("amount_usdt", sa.Float, nullable=False),
        sa.Column("payment_method", sa.String(16), default="crypto"),
        sa.Column("status", sa.String(16), default="pending"),
        sa.Column("txid", sa.String(128), unique=True),
        sa.Column("screenshot_path", sa.String(512)),
        sa.Column("usdt_address_id", sa.Integer, sa.ForeignKey("usdt_addresses.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String(64)),
        sa.Column("reject_reason", sa.String(256)),
        sa.Column("tronscan_verified", sa.Boolean),
        sa.Column("tronscan_data", postgresql.JSON),
        sa.Column("deposit_address", sa.String(128)),
        sa.Column("network", sa.String(16)),
        sa.Column("address_expires_at", sa.DateTime(timezone=True)),
        sa.Column("address_generated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def _create_system_tables() -> None:
    # system_configs
    op.create_table(
        "system_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(128), unique=True, nullable=False),
        sa.Column("value", sa.Text),
        sa.Column("is_encrypted", sa.Boolean, default=False),
        sa.Column("description", sa.String(256)),
        sa.Column("updated_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # system_logs
    op.create_table(
        "system_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("user_id", sa.Integer),
        sa.Column("account_id", sa.Integer),
        sa.Column("platform", sa.String(32)),
        sa.Column("details", postgresql.JSON),
        sa.Column("extra", postgresql.JSON),
        sa.Column("resolved", sa.Boolean, default=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_note", sa.String(512)),
        sa.Column("alert_sent", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_system_logs_level_created", "system_logs", ["level", "created_at"])
    op.create_index("ix_system_logs_module_created", "system_logs", ["module", "created_at"])
    op.create_index("ix_system_logs_cleanup", "system_logs", ["created_at"])

    # platform_errors
    op.create_table(
        "platform_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("error_type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("affected_accounts", sa.Integer, default=1),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # daily_stats
    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("platform", sa.String(32)),
        sa.Column("success_count", sa.Integer, default=0),
        sa.Column("fail_count", sa.Integer, default=0),
        sa.Column("total_posts_sent", sa.Integer, default=0),
        sa.Column("new_users", sa.Integer, default=0),
        sa.Column("new_accounts", sa.Integer, default=0),
        sa.Column("ai_calls", sa.Integer, default=0),
        sa.Column("downloads", sa.Integer, default=0),
        sa.UniqueConstraint("date", "platform", name="uq_daily_stat"),
    )

    # rate_limit_queue
    op.create_table(
        "rate_limit_queue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rate_limit_user_action", "rate_limit_queue", ["user_id", "action", "created_at"])

    # bookmarks
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("account_name", sa.String(256)),
        sa.Column("title", sa.String(512)),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("post_hash", sa.String(64), nullable=False),
        sa.Column("thumbnail_url", sa.String(1024)),
        sa.Column("has_video", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "post_hash", name="uq_user_bookmark"),
    )
    op.create_index("ix_bookmarks_user", "bookmarks", ["user_id", "created_at"])

def _create_support_tables() -> None:
    # support_tickets
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_number", sa.String(16), unique=True, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ticket_messages
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_type", sa.String(10), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("attachments", postgresql.JSON, default=list),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def _add_missing_columns() -> None:
    # Add platforms_json to plan_configs
    op.add_column("plan_configs", sa.Column("platforms_json", postgresql.JSON, nullable=True))

    # Add bookmark_count to users
    op.add_column("users", sa.Column("bookmark_count", sa.Integer, default=0))



    # plan_configs - add features_json and prices (guard: may already exist in create_table)
    try:
        op.add_column("plan_configs", sa.Column("features_json", sa.JSON, nullable=True))
    except Exception:
        pass
    try:
        op.add_column("plan_configs", sa.Column("price_monthly", sa.Float, default=0.0))
        op.add_column("plan_configs", sa.Column("price_biannual", sa.Float, default=0.0))
        op.add_column("plan_configs", sa.Column("price_yearly", sa.Float, default=0.0))
    except Exception:
        pass

    # ── Missing user fields (added in models.py but absent from initial migration) ──
    try:
        op.add_column("users", sa.Column("hide_spam_posts", sa.Boolean, server_default="false"))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("email", sa.String(256), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("email_digest_enabled", sa.Boolean, server_default="false"))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("email_unsubscribe_token", sa.String(64), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("share_prompt_count", sa.Integer, server_default="0"))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("share_prompt_last_at", sa.DateTime(timezone=True), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("credit_expires_at", sa.DateTime(timezone=True), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("credit_plan", sa.String(16), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("credit_granted_by", sa.String(64), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("users", sa.Column("original_plan_before_grace", sa.String(16), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    for table in [
        "bookmarks", "rate_limit_queue", "daily_stats", "platform_errors",
        "system_logs", "ticket_messages", "support_tickets",
        "system_configs", "transactions", "usdt_addresses",
        "sent_posts", "accounts", "categories", "users", "plan_configs",
    ]:
        op.drop_table(table)
