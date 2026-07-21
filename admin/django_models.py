"""
SocialtoFeed — Django ORM Models
Mirrors the SQLAlchemy schema so Django Admin can read/write the same DB.
These are the authoritative Django models used only by the admin panel.
"""

from django.db import models


class UserProxy(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=64, null=True, blank=True)
    first_name = models.CharField(max_length=128, null=True, blank=True)
    plan = models.CharField(
        max_length=16,
        choices=[("free", "Free"), ("pro", "Pro"), ("premium", "Premium")],
        default="free",
    )
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    subscription_paused_at = models.DateTimeField(null=True, blank=True)
    subscription_pause_used = models.BooleanField(default=False)
    language = models.CharField(max_length=10, default="en")

    # AI
    ai_summarize = models.BooleanField(default=False)
    ai_translate = models.BooleanField(default=False)
    ai_translate_lang = models.CharField(max_length=10, null=True, blank=True)
    ai_show_original = models.BooleanField(default=True)
    ai_categorize = models.BooleanField(default=False)
    ai_spam_tag = models.BooleanField(default=False)
    daily_ai_count = models.IntegerField(default=0)

    # Digest
    digest_enabled = models.BooleanField(default=False)
    digest_interval_hours = models.IntegerField(default=24)
    digest_next_send = models.DateTimeField(null=True, blank=True)

    # Channel forward
    channel_forward_id = models.BigIntegerField(null=True, blank=True)
    channel_forward_errors = models.SmallIntegerField(default=0)

    # Footer
    footer_enabled = models.BooleanField(default=True)
    footer_post_counter = models.IntegerField(default=0)

    # Referral (added v3.0 — must match users table exactly)
    referral_code = models.CharField(max_length=16, unique=True, null=True, blank=True)
    referred_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals", db_column="referred_by_id",
    )
    referral_bonus_accounts = models.IntegerField(default=0)
    referral_count  = models.IntegerField(default=0)   # v3.0
    referral_points = models.IntegerField(default=0)   # v3.0

    # Rate limit
    daily_request_count = models.IntegerField(default=0)
    last_request_reset  = models.DateTimeField(null=True, blank=True)
    last_expiry_warning_at = models.DateTimeField(null=True, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    # Status
    is_banned   = models.BooleanField(default=False)
    ban_reason  = models.CharField(max_length=256, null=True, blank=True)

    # Bookmark / spam
    bookmark_count   = models.IntegerField(default=0)
    hide_spam_posts  = models.BooleanField(default=False)

    # Email
    email                   = models.EmailField(null=True, blank=True)
    email_digest_enabled    = models.BooleanField(default=False)
    email_unsubscribe_token = models.CharField(max_length=64, null=True, blank=True)

    # Share prompt
    share_prompt_count   = models.IntegerField(default=0)
    share_prompt_last_at = models.DateTimeField(null=True, blank=True)

    # Credit (free subscription granted by admin)
    credit_expires_at  = models.DateTimeField(null=True, blank=True)
    credit_plan        = models.CharField(max_length=16, null=True, blank=True)
    credit_granted_by  = models.CharField(max_length=64, null=True, blank=True)

    # Grace period
    grace_until                = models.DateTimeField(null=True, blank=True)
    original_plan_before_grace = models.CharField(max_length=16, null=True, blank=True)

    metadata   = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        managed = False  # SQLAlchemy manages the schema
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.username or self.telegram_id} [{self.plan}]"


class CategoryProxy(models.Model):
    user = models.ForeignKey(UserProxy, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=64)
    emoji = models.CharField(max_length=8, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    sort_order = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "categories"
        managed = False
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return f"{self.emoji or '📁'} {self.name}"


class AccountProxy(models.Model):
    user = models.ForeignKey(UserProxy, on_delete=models.CASCADE, related_name="accounts")
    category = models.ForeignKey(
        CategoryProxy, null=True, blank=True, on_delete=models.SET_NULL
    )
    platform = models.CharField(max_length=32)
    identifier = models.CharField(max_length=256)
    display_name = models.CharField(max_length=256, null=True, blank=True)
    feed_url = models.CharField(max_length=512, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    custom_interval_minutes = models.IntegerField(null=True, blank=True)
    next_fetch_at = models.DateTimeField(null=True, blank=True)
    last_successful_fetch = models.DateTimeField(null=True, blank=True)
    error_count = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_errors = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts"
        managed = False
        verbose_name = "Account"
        verbose_name_plural = "Accounts"

    def __str__(self):
        return f"{self.platform}:{self.display_name or self.identifier}"


class SentPostProxy(models.Model):
    account = models.ForeignKey(AccountProxy, on_delete=models.CASCADE)
    post_id = models.CharField(max_length=256, null=True, blank=True)
    post_hash = models.CharField(max_length=64)
    title = models.CharField(max_length=512, null=True, blank=True)
    url = models.CharField(max_length=1024, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sent_posts"
        managed = False
        verbose_name = "Sent Post"
        verbose_name_plural = "Sent Posts"


class PlanConfigProxy(models.Model):
    plan = models.CharField(
        max_length=16,
        choices=[("free", "Free"), ("pro", "Pro"), ("premium", "Premium")],
        unique=True,
    )
    max_accounts = models.IntegerField(default=5)
    max_categories = models.IntegerField(default=5)
    max_open_tickets = models.IntegerField(default=0)
    ai_enabled = models.BooleanField(default=False)
    video_download = models.BooleanField(default=False)
    digest_enabled = models.BooleanField(default=False)
    channel_forward = models.BooleanField(default=False)
    export_csv = models.BooleanField(default=False)
    export_json = models.BooleanField(default=False)
    stats_enabled = models.BooleanField(default=False)
    pause_enabled = models.BooleanField(default=False)
    custom_interval = models.BooleanField(default=False)
    ai_daily_limit = models.IntegerField(default=0)
    price_monthly = models.FloatField(default=0.0)
    price_biannual = models.FloatField(default=0.0)
    price_yearly = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_configs"
        managed = False
        verbose_name = "Plan Config"
        verbose_name_plural = "Plan Configs"

    def __str__(self):
        return f"{self.plan.upper()} — ${self.price_monthly}/mo"


class USDTAddressProxy(models.Model):
    label = models.CharField(max_length=64)
    address = models.CharField(max_length=128)
    network = models.CharField(max_length=32, default="TRC20")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "usdt_addresses"
        managed = False
        verbose_name = "USDT Address"
        verbose_name_plural = "USDT Addresses"

    def __str__(self):
        return f"{self.label} ({'default' if self.is_default else 'active' if self.is_active else 'inactive'})"


class TransactionProxy(models.Model):
    user = models.ForeignKey(UserProxy, on_delete=models.CASCADE, related_name="transactions")
    plan = models.CharField(max_length=16)
    period = models.CharField(max_length=16)
    amount_usdt = models.FloatField()
    payment_method = models.CharField(max_length=16, default="usdt")
    status = models.CharField(
        max_length=16,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
    )
    txid = models.CharField(max_length=128, null=True, blank=True, unique=True)
    screenshot_path = models.CharField(max_length=512, null=True, blank=True)
    usdt_address = models.ForeignKey(
        USDTAddressProxy, null=True, blank=True, on_delete=models.SET_NULL
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=64, null=True, blank=True)
    reject_reason = models.CharField(max_length=256, null=True, blank=True)
    tronscan_verified = models.BooleanField(null=True, blank=True)
    tronscan_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "transactions"
        managed = False
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"TX#{self.id} {self.plan}/{self.period} {self.status}"


class SystemConfigProxy(models.Model):
    key = models.CharField(max_length=128, unique=True)
    value = models.TextField(null=True, blank=True)
    is_encrypted = models.BooleanField(default=False)
    description = models.CharField(max_length=256, null=True, blank=True)
    updated_by = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_configs"
        managed = False
        verbose_name = "System Config"
        verbose_name_plural = "System Configs"
        ordering = ["key"]

    def __str__(self):
        return self.key


class SupportTicketProxy(models.Model):
    ticket_number = models.CharField(max_length=16, unique=True)
    user = models.ForeignKey(UserProxy, on_delete=models.CASCADE, related_name="tickets")
    subject = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16,
        choices=[("open", "Open"), ("answered", "Answered"), ("closed", "Closed")],
        default="open",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_tickets"
        managed = False
        verbose_name = "Support Ticket"
        verbose_name_plural = "Support Tickets"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_number} [{self.status}]"


class TicketMessageProxy(models.Model):
    ticket = models.ForeignKey(SupportTicketProxy, on_delete=models.CASCADE)
    sender_type = models.CharField(max_length=10)
    message = models.TextField(null=True, blank=True)
    attachments = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_messages"
        managed = False
        verbose_name = "Ticket Message"
        verbose_name_plural = "Ticket Messages"
        ordering = ["created_at"]


class SystemLogProxy(models.Model):
    level = models.CharField(max_length=16)
    module = models.CharField(max_length=32)
    message = models.TextField()
    user_id = models.IntegerField(null=True, blank=True)
    account_id = models.IntegerField(null=True, blank=True)
    platform = models.CharField(max_length=32, null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    extra = models.JSONField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_note = models.CharField(max_length=512, null=True, blank=True)
    alert_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "system_logs"
        managed = False
        verbose_name = "System Log"
        verbose_name_plural = "System Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.level}] {self.module}: {self.message[:60]}"


class PlatformErrorProxy(models.Model):
    platform = models.CharField(max_length=32)
    error_type = models.CharField(max_length=64)
    message = models.TextField(null=True, blank=True)
    affected_accounts = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_errors"
        managed = False
        verbose_name = "Platform Error"
        verbose_name_plural = "Platform Errors"
        ordering = ["-created_at"]


class DailyStatProxy(models.Model):
    date = models.CharField(max_length=10)
    platform = models.CharField(max_length=32, null=True, blank=True)
    success_count = models.IntegerField(default=0)
    fail_count = models.IntegerField(default=0)
    total_posts_sent = models.IntegerField(default=0)
    new_users = models.IntegerField(default=0)
    new_accounts = models.IntegerField(default=0)
    ai_calls = models.IntegerField(default=0)
    downloads = models.IntegerField(default=0)

    class Meta:
        db_table = "daily_stats"
        managed = False
        verbose_name = "Daily Stat"
        verbose_name_plural = "Daily Stats"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} / {self.platform or 'all'}"


class RateLimitEntryProxy(models.Model):
    user_id = models.IntegerField()
    action = models.CharField(max_length=64)
    ip_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rate_limit_queue"
        managed = False
