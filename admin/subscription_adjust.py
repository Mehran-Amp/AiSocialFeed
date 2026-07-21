"""
SocialtoFeed — Admin Subscription Adjustment  v4.0

Allows admin to:
  - Add/remove months from subscription
  - Change plan (Pro / Premium / Free)
  - Set exact expiry date

Accessible from Django Admin user change page.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse

logger = logging.getLogger(__name__)

PLAN_CHOICES = [("free", "🆓 Free"), ("pro", "⭐️ Pro"), ("premium", "💎 Premium")]


class SubscriptionAdjustMixin:
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:user_id>/adjust-subscription/",
                self.admin_site.admin_view(self.adjust_subscription_view),
                name="adjust_subscription",
            ),
        ]
        return custom + urls

    def adjust_subscription_view(self, request: HttpRequest, user_id: int) -> HttpResponse:
        from admin.django_models import UserProxy
        try:
            user = UserProxy.objects.get(pk=user_id)
        except UserProxy.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect("admin:stf_admin_userproxy_changelist")

        if request.method == "POST":
            # Fix 4: handle plan change + date adjust in one form
            new_plan   = request.POST.get("plan", user.plan)
            action     = request.POST.get("action", "set")  # add | remove | set
            months     = int(request.POST.get("months", 0))
            exact_date = request.POST.get("exact_date", "").strip()
            reason     = request.POST.get("reason", "").strip()

            now = datetime.now(timezone.utc)
            base = (user.subscription_expires_at
                    if user.subscription_expires_at and user.subscription_expires_at > now
                    else now)

            if exact_date:
                try:
                    new_expiry = datetime.strptime(exact_date, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc)
                except ValueError:
                    messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
                    new_expiry = None
            elif months > 0:
                delta = timedelta(days=months * 30)
                new_expiry = base + delta if action == "add" else max(base - delta, now)
            else:
                new_expiry = user.subscription_expires_at

            if new_expiry:
                updates = dict(plan=new_plan, subscription_expires_at=new_expiry)
                if new_plan == "free":
                    updates["subscription_expires_at"] = None
                UserProxy.objects.filter(pk=user.pk).update(**updates)
                user.plan = new_plan
                user.subscription_expires_at = updates.get("subscription_expires_at")
                logger.info(
                    f"Admin {request.user.username} changed user={user.telegram_id} "
                    f"plan={new_plan} expiry={new_expiry} reason={reason}"
                )
                _notify_user_adjustment(
                    user.telegram_id, user.language,
                    new_plan, new_expiry, reason,
                )
                messages.success(
                    request,
                    f"✅ @{user.username or user.telegram_id} → "
                    f"{new_plan.upper()} until "
                    f"{new_expiry.strftime('%Y-%m-%d') if new_expiry else 'N/A'}",
                )
                return redirect(reverse("admin:stf_admin_userproxy_change", args=[user_id]))

        context = {
            "title":           f"Adjust Subscription — @{user.username or user.telegram_id}",
            "user":            user,
            "current_expiry":  user.subscription_expires_at,
            "current_plan":    user.plan,
            "plan_choices":    PLAN_CHOICES,
            "opts":            UserProxy._meta,
            "cancel_url":      reverse("admin:stf_admin_userproxy_change", args=[user.pk]),
        }
        return render(request, "admin/adjust_subscription.html", context)


def _notify_user_adjustment(telegram_id, lang, plan, expiry, reason):
    try:
        import asyncio
        from bot.utils.telegram_utils import safe_send_message
        expiry_str = expiry.strftime("%Y-%m-%d") if expiry else "—"
        f = lang == "fa"
        plan_icons = {"pro": "⭐️", "premium": "💎", "free": "🆓"}
        icon = plan_icons.get(plan, "ℹ️")
        if f:
            msg = (f"{icon} <b>پلن شما تغییر کرد!</b>\n\n"
                   f"پلن جدید: <b>{plan.upper()}</b>\n"
                   f"تاریخ انقضا: <b>{expiry_str}</b>")
        else:
            msg = (f"{icon} <b>Your plan has been updated!</b>\n\n"
                   f"New plan: <b>{plan.upper()}</b>\n"
                   f"Expires: <b>{expiry_str}</b>")
        if reason:
            msg += f"\n\n📝 Note: {reason}"
        loop = asyncio.new_event_loop()
        loop.run_until_complete(safe_send_message(telegram_id, msg, parse_mode="HTML"))
        loop.close()
    except Exception as e:
        logger.error(f"Failed to notify user {telegram_id}: {e}")
