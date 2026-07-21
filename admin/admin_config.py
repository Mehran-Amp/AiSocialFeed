"""
SocialtoFeed — Django Admin Registration
All models with custom actions, filters, and debug tools.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from django.contrib import admin, messages
from django.db import models as django_models
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from admin.subscription_adjust import SubscriptionAdjustMixin
from admin.broadcast import BroadcastAdminMixin

# Import SQLAlchemy models mapped to Django proxy models
# (In production: use Django ORM models that mirror the SQLAlchemy schema)
# For simplicity, we use Django's admin with raw DB access via custom views

from .django_models import (
    UserProxy, TransactionProxy, USDTAddressProxy,
    PlanConfigProxy, SystemConfigProxy, SupportTicketProxy,
    SystemLogProxy, DailyStatProxy,
)


# ─────────────────────────────────────────────
#  Users
# ─────────────────────────────────────────────

@admin.register(UserProxy)
class UserAdmin(SubscriptionAdjustMixin, admin.ModelAdmin):
    list_display = (
        "telegram_id", "username", "first_name",
        "plan_badge", "subscription_expires_at",
        "is_banned", "last_active_at", "created_at",
        "adjust_link", "tg_admin_link",
    )
    list_filter = ("plan", "is_banned")
    search_fields = ("telegram_id", "username", "first_name")
    readonly_fields = (
        "telegram_id", "referral_code", "referral_count", "referral_points",
        "created_at", "last_active_at", "daily_request_count",
        "share_prompt_count", "bookmark_count",
    )
    list_per_page = 50
    ordering = ("-created_at",)

    fieldsets = (
        ("Identity", {
            "fields": ("telegram_id", "username", "first_name", "language")
        }),
        ("Plan & Subscription", {
            "fields": ("plan", "subscription_expires_at", "subscription_pause_used",
                       "referral_bonus_accounts", "credit_plan", "credit_expires_at",
                       "grace_until", "original_plan_before_grace")
        }),
        ("AI Settings", {
            "classes": ("collapse",),
            "fields": ("ai_summarize", "ai_translate", "ai_translate_lang",
                       "ai_categorize", "ai_spam_tag", "daily_ai_count"),
        }),
        ("Features", {
            "classes": ("collapse",),
            "fields": ("digest_enabled", "digest_interval_hours",
                       "channel_forward_id", "footer_enabled",
                       "hide_spam_posts", "email_digest_enabled"),
        }),
        ("Referral", {
            "classes": ("collapse",),
            "fields": ("referral_code", "referral_count", "referral_points"),
        }),
        ("Status", {
            "fields": ("is_banned", "ban_reason",
                       "last_active_at", "created_at"),
        }),
    )

    actions = [
        "set_pro_30d", "set_pro_90d",
        "set_premium_30d", "set_premium_90d",
        "downgrade_to_free",
        "ban_users", "unban_users",
    ]

    # ── Direct plan actions (no async, no Celery — pure SQL UPDATE) ──────────

    @admin.action(description="⭐️ Set Pro — 30 days")
    def set_pro_30d(self, request, queryset):
        self._set_plan(request, queryset, "pro", 30)

    @admin.action(description="⭐️ Set Pro — 90 days")
    def set_pro_90d(self, request, queryset):
        self._set_plan(request, queryset, "pro", 90)

    @admin.action(description="💎 Set Premium — 30 days")
    def set_premium_30d(self, request, queryset):
        self._set_plan(request, queryset, "premium", 30)

    @admin.action(description="💎 Set Premium — 90 days")
    def set_premium_90d(self, request, queryset):
        self._set_plan(request, queryset, "premium", 90)

    @admin.action(description="🆓 Downgrade to Free")
    def downgrade_to_free(self, request, queryset):
        queryset.update(plan="free", subscription_expires_at=None,
                        credit_plan=None, credit_expires_at=None)
        self.message_user(request, f"{queryset.count()} user(s) set to Free.")

    def _set_plan(self, request, queryset, plan: str, days: int):
        """Direct DB update — no async, no external calls, never fails."""
        from datetime import datetime, timedelta, timezone
        new_expiry = datetime.now(timezone.utc) + timedelta(days=days)
        updated = queryset.update(
            plan=plan,
            subscription_expires_at=new_expiry,
            credit_plan=None,
            credit_expires_at=None,
        )
        self.message_user(
            request,
            f"✅ {updated} user(s) set to {plan.upper()} until "
            f"{new_expiry.strftime('%Y-%m-%d')}.",
            messages.SUCCESS,
        )

    @admin.display(description="Adjust")
    def adjust_link(self, obj):
        from django.urls import reverse
        url = reverse("admin:adjust_subscription", args=[obj.pk])
        return format_html('<a href="{}" class="button">⚙️ Adjust</a>', url)

    @admin.display(description="TG Admin")
    def tg_admin_link(self, obj):
        """Deep-link button that opens the Telegram bot at the user detail view."""
        from django.conf import settings
        bot_username = getattr(settings, "BOT_USERNAME", "AiSocialFeedBot")
        # Opens bot with /start param — bot recognises admin and shows user detail
        url = f"https://t.me/{bot_username}?start=adminuser_{obj.pk}"
        return format_html(
            '<a href="{}" target="_blank" class="button" '
            'style="background:#2481cc;color:#fff;padding:2px 8px;border-radius:4px;">'
            '📱 Open in TG</a>',
            url,
        )

    @admin.display(description="Plan")
    def plan_badge(self, obj):
        colors = {"free": "gray", "pro": "blue", "premium": "gold"}
        color = colors.get(obj.plan, "gray")
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, obj.plan.upper()
        )

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        queryset.update(is_banned=True)
        self.message_user(request, f"{queryset.count()} user(s) banned.", messages.WARNING)

    @admin.action(description="Unban selected users")
    def unban_users(self, request, queryset):
        queryset.update(is_banned=False)
        self.message_user(request, f"{queryset.count()} user(s) unbanned.")

    @admin.action(description="Downgrade to Free plan")
    def downgrade_to_free(self, request, queryset):
        queryset.update(plan="free", subscription_expires_at=None)
        self.message_user(request, f"{queryset.count()} user(s) downgraded.")


# ─────────────────────────────────────────────
#  Transactions
# ─────────────────────────────────────────────

@admin.register(TransactionProxy)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user_link", "plan", "period",
        "amount_usdt", "status_badge",
        "payment_method", "txid_link",
        "screenshot_preview", "created_at",
    )
    list_filter = ("status", "plan", "period", "payment_method")
    search_fields = ("txid", "user__telegram_id", "user__username")
    readonly_fields = (
        "user", "plan", "period", "amount_usdt", "payment_method",
        "txid", "screenshot_path", "tronscan_data", "created_at",
        "txid_link", "screenshot_preview",
    )
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ["approve_transactions", "reject_transactions"]

    fieldsets = (
        ("Transaction", {
            "fields": ("user", "plan", "period", "amount_usdt", "payment_method", "created_at")
        }),
        ("Proof", {
            "fields": ("txid", "txid_link", "screenshot_path", "screenshot_preview")
        }),
        ("Review", {
            "fields": ("status", "reviewed_at", "reviewed_by", "reject_reason",
                       "tronscan_verified", "tronscan_data")
        }),
    )

    @admin.display(description="User")
    def user_link(self, obj):
        url = reverse("admin:stf_admin_userproxy_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url,
                          obj.user.username or obj.user.telegram_id)

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"pending": "orange", "approved": "green", "rejected": "red"}
        color = colors.get(obj.status, "gray")
        return format_html(
            '<b style="color:{};">{}</b>', color, obj.status.upper()
        )

    @admin.display(description="TxID")
    def txid_link(self, obj):
        if not obj.txid:
            return "—"
        url = f"https://tronscan.org/#/transaction/{obj.txid}"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url, obj.txid[:20] + "..."
        )

    @admin.display(description="Screenshot")
    def screenshot_preview(self, obj):
        if not obj.screenshot_path:
            return "—"
        if obj.screenshot_path.startswith("tg:"):
            return format_html('<span title="{}">📎 Telegram File</span>', obj.screenshot_path)
        return format_html(
            '<a href="{}" target="_blank">🖼 View</a>', obj.screenshot_path
        )

    @admin.action(description="✅ Approve selected transactions")
    def approve_transactions(self, request, queryset):
        from .services import activate_subscription
        count = 0
        for tx in queryset.filter(status="pending"):
            try:
                activate_subscription(tx, request.user.username)
                count += 1
            except Exception as e:
                self.message_user(request, f"Error for tx {tx.id}: {e}", messages.ERROR)
        self.message_user(request, f"{count} transaction(s) approved.", messages.SUCCESS)

    @admin.action(description="❌ Reject selected transactions")
    def reject_transactions(self, request, queryset):
        queryset.filter(status="pending").update(
            status="rejected",
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by=request.user.username,
        )
        self.message_user(request, f"{queryset.count()} transaction(s) rejected.", messages.WARNING)


# ─────────────────────────────────────────────
#  USDT Addresses
# ─────────────────────────────────────────────

@admin.register(USDTAddressProxy)
class USDTAddressAdmin(admin.ModelAdmin):
    list_display = ("label", "address_masked", "network", "is_active", "is_default", "updated_at")
    list_editable = ("is_active", "is_default")
    ordering = ("-is_default", "label")

    @admin.display(description="Address")
    def address_masked(self, obj):
        if not obj.address:
            return "—"
        return f"{obj.address[:10]}...{obj.address[-6:]}"

    def save_model(self, request, obj, form, change):
        # Enforce max 3 addresses
        if not change:
            from .django_models import USDTAddressProxy
            if USDTAddressProxy.objects.count() >= 3:
                messages.error(request, "Maximum 3 USDT addresses allowed.")
                return
        # Only one default
        if obj.is_default:
            USDTAddressProxy.objects.exclude(pk=obj.pk).update(is_default=False)
        super().save_model(request, obj, form, change)


# ─────────────────────────────────────────────
#  Plan Config
# ─────────────────────────────────────────────

@admin.register(PlanConfigProxy)
class PlanConfigAdmin(admin.ModelAdmin):
    list_display = (
        "plan", "max_accounts", "max_categories",
        "price_monthly", "price_biannual", "price_yearly",
        "ai_enabled", "video_download", "updated_at",
    )
    list_editable = (
        "max_accounts", "price_monthly", "price_biannual", "price_yearly",
    )
    ordering = ("plan",)

    fieldsets = (
        ("Plan", {"fields": ("plan",)}),
        ("Limits", {
            "fields": ("max_accounts", "max_categories", "max_open_tickets",
                       "ai_daily_limit"),
        }),
        ("Features", {
            "fields": ("ai_enabled", "video_download", "digest_enabled",
                       "channel_forward", "export_csv", "export_json",
                       "stats_enabled", "pause_enabled", "custom_interval"),
        }),
        ("Pricing (USDT)", {
            "fields": ("price_monthly", "price_biannual", "price_yearly"),
        }),
    )

    def has_add_permission(self, request):
        return False  # Plans are seeded, not created manually

    def has_delete_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────
#  System Config (API Keys etc.)
# ─────────────────────────────────────────────

@admin.register(SystemConfigProxy)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ("key", "value_masked", "is_encrypted", "description", "updated_at")
    readonly_fields = ("key", "updated_at")
    search_fields = ("key",)

    @admin.display(description="Value")
    def value_masked(self, obj):
        if obj.is_encrypted and obj.value:
            from bot.utils.encryption import mask
            return mask(obj.value)
        return (obj.value or "")[:50]

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user.username
        # Encrypt if flagged
        if obj.is_encrypted and obj.value and not obj.value.startswith("gAAAAA"):
            from bot.utils.encryption import encrypt
            obj.value = encrypt(obj.value)
        super().save_model(request, obj, form, change)
        # Invalidate DeepSeek client if key changed
        if obj.key == "deepseek_api_key":
            import bot.services.ai_service as ai_svc
            ai_svc._client = None
            messages.success(request, "DeepSeek client will reconnect with new key.")


# ─────────────────────────────────────────────
#  Support Tickets
# ─────────────────────────────────────────────

@admin.register(SupportTicketProxy)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_number", "user_link", "subject",
        "status_badge", "created_at",
    )
    list_filter = ("status", "subject")
    search_fields = ("ticket_number", "user__username", "user__telegram_id")
    readonly_fields = ("ticket_number", "user", "subject", "created_at", "messages_display")
    ordering = ("-created_at",)
    actions = ["close_tickets"]

    @admin.display(description="User")
    def user_link(self, obj):
        url = reverse("admin:stf_admin_userproxy_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url,
                          obj.user.username or str(obj.user.telegram_id))

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"open": "orange", "answered": "green", "closed": "gray"}
        return format_html(
            '<b style="color:{};">{}</b>',
            colors.get(obj.status, "gray"), obj.status.upper()
        )

    @admin.display(description="Messages")
    def messages_display(self, obj):
        msgs = obj.ticketmessageproxy_set.order_by("created_at").all()
        html = '<div style="max-height:400px;overflow-y:auto;border:1px solid #ddd;padding:10px;">'
        for m in msgs:
            bg = "#e8f4fd" if m.sender_type == "admin" else "#f9f9f9"
            html += (
                f'<div style="background:{bg};margin:5px 0;padding:8px;border-radius:4px;">'
                f'<b>{m.sender_type.upper()}</b> · {m.created_at.strftime("%Y-%m-%d %H:%M")}<br>'
                f'{m.message}</div>'
            )
        html += "</div>"
        return mark_safe(html)

    @admin.action(description="Close selected tickets")
    def close_tickets(self, request, queryset):
        queryset.update(status="closed", closed_at=datetime.now(timezone.utc))
        self.message_user(request, f"{queryset.count()} ticket(s) closed.")


# ─────────────────────────────────────────────
#  System Logs
# ─────────────────────────────────────────────

@admin.register(SystemLogProxy)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "level_badge", "module",
        "message_short", "user_id", "resolved",
    )
    list_filter = ("level", "module", "resolved")
    search_fields = ("message", "user_id")
    readonly_fields = (
        "level", "module", "message", "user_id", "account_id",
        "platform", "details_pretty", "created_at",
    )
    ordering = ("-created_at",)
    list_per_page = 100
    actions = ["mark_resolved", "export_as_json"]
    date_hierarchy = "created_at"

    @admin.display(description="Level")
    def level_badge(self, obj):
        colors = {
            "DEBUG": "gray", "INFO": "blue",
            "WARNING": "orange", "ERROR": "red", "CRITICAL": "darkred",
        }
        return format_html(
            '<b style="color:{};">{}</b>',
            colors.get(obj.level, "black"), obj.level
        )

    @admin.display(description="Message")
    def message_short(self, obj):
        return (obj.message or "")[:80]

    @admin.display(description="Details")
    def details_pretty(self, obj):
        if not obj.details:
            return "—"
        return format_html(
            "<pre style='max-height:300px;overflow:auto;font-size:11px;'>{}</pre>",
            json.dumps(obj.details, indent=2, ensure_ascii=False)[:3000]
        )

    @admin.action(description="Mark as resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True, resolved_at=datetime.now(timezone.utc))
        self.message_user(request, f"{queryset.count()} log(s) marked resolved.")

    @admin.action(description="📋 Export as JSON (Debug Report)")
    def export_as_json(self, request, queryset):
        data = [
            {
                "id": log.id,
                "time": log.created_at.isoformat(),
                "level": log.level,
                "module": log.module,
                "message": log.message,
                "user_id": log.user_id,
                "details": log.details,
            }
            for log in queryset[:500]
        ]
        response = HttpResponse(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            content_type="application/json",
        )
        response["Content-Disposition"] = 'attachment; filename="stf_debug_export.json"'
        return response

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "full-debug-report/",
                self.admin_site.admin_view(self.full_debug_report),
                name="full_debug_report",
            ),
        ]
        return custom + urls

    def full_debug_report(self, request):
        """Generate full system debug report for download."""
        async def _gen():
            from bot.utils.logger import generate_debug_report
            return await generate_debug_report()

        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(_gen())
        finally:
            loop.close()

        response = HttpResponse(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            content_type="application/json",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="stf_debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        )
        return response


# ─────────────────────────────────────────────
#  Daily Stats (read-only dashboard)
# ─────────────────────────────────────────────

@admin.register(DailyStatProxy)
class DailyStatAdmin(admin.ModelAdmin):
    list_display = (
        "date", "platform", "total_posts_sent",
        "success_count", "fail_count",
        "new_users", "ai_calls",
    )
    list_filter = ("platform",)
    ordering = ("-date",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────
#  Admin Credit Management
# ─────────────────────────────────────────────

class AdminCreditLogAdmin(admin.ModelAdmin):
    list_display = ("user_telegram_id", "plan", "days", "reason",
                    "granted_by", "granted_at", "expires_at")
    list_filter = ("plan", "granted_by")
    search_fields = ("user__telegram_id", "granted_by", "reason")
    readonly_fields = ("granted_at",)
    ordering = ("-granted_at",)

    def user_telegram_id(self, obj):
        return obj.user.telegram_id if obj.user else "-"
    user_telegram_id.short_description = "Telegram ID"


class UserAdminWithCredit(admin.ModelAdmin):
    """Extended User admin with credit management."""
    list_display = ("telegram_id", "username", "plan", "credit_plan",
                    "credit_expires_at", "subscription_expires_at", "created_at")
    list_filter = ("plan", "credit_plan", "language")
    search_fields = ("telegram_id", "username", "first_name")
    readonly_fields = ("telegram_id", "created_at", "last_active_at")

    actions = ["grant_7day_pro", "grant_30day_pro",
               "grant_7day_premium", "grant_30day_premium",
               "revoke_credit"]

    @admin.action(description="🎁 Grant 7 days Pro")
    def grant_7day_pro(self, request, queryset):
        self._grant_credit(request, queryset, "pro", 7)

    @admin.action(description="🎁 Grant 30 days Pro")
    def grant_30day_pro(self, request, queryset):
        self._grant_credit(request, queryset, "pro", 30)

    @admin.action(description="🎁 Grant 7 days Premium")
    def grant_7day_premium(self, request, queryset):
        self._grant_credit(request, queryset, "premium", 7)

    @admin.action(description="🎁 Grant 30 days Premium")
    def grant_30day_premium(self, request, queryset):
        self._grant_credit(request, queryset, "premium", 30)

    @admin.action(description="❌ Revoke credit")
    def revoke_credit(self, request, queryset):
        import asyncio
        from bot.services.plan_service import revoke_credit
        count = 0
        for user in queryset:
            asyncio.run(revoke_credit(user.id, str(request.user)))
            count += 1
        self.message_user(request, f"✅ Credit revoked from {count} users.")

    def _grant_credit(self, request, queryset, plan: str, days: int):
        import asyncio
        from bot.services.plan_service import grant_credit
        from bot.models import PlanType
        count = 0
        for user in queryset:
            try:
                asyncio.run(grant_credit(
                    user.id, PlanType(plan), days,
                    granted_by=str(request.user),
                    reason=f"Admin grant via panel"
                ))
                count += 1
            except Exception as e:
                self.message_user(request, f"❌ Error for {user.telegram_id}: {e}", level="ERROR")
        self.message_user(request, f"✅ {days}-day {plan} granted to {count} users.")

