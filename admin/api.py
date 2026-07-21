"""
AiSocialFeed — Admin API Endpoints
REST endpoints for admin panel dashboard features.
All endpoints require Django admin session authentication.
"""
from __future__ import annotations
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET

logger = logging.getLogger(__name__)


def admin_api(view_func):
    """Decorator: require staff login for all API endpoints."""
    return staff_member_required(view_func, login_url="/admin/login/")


# ── 1. Cookie Status ──────────────────────────────────────────────────────────

@admin_api
@require_GET
def cookie_status(request):
    """Return RSSHub cookie age and health status for Twitter/Instagram/TikTok."""
    import redis
    from django.conf import settings

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        now = datetime.now(timezone.utc)

        platforms = {
            "twitter":   "RSSHUB_COOKIE_TWITTER",
            "instagram": "RSSHUB_COOKIE_INSTAGRAM",
            "tiktok":    "RSSHUB_COOKIE_TIKTOK",
        }

        result = {}
        for platform, env_key in platforms.items():
            updated_key = f"cookie_updated_at:{platform}"
            updated_raw = r.get(updated_key)

            if updated_raw:
                updated_at = datetime.fromisoformat(updated_raw)
                age_days = (now - updated_at).days
                status = "ok" if age_days < 14 else ("warning" if age_days < 25 else "expired")
                last_updated = updated_at.strftime("%Y-%m-%d")
            else:
                # No record — cookie was never explicitly set via admin
                import os
                has_cookie = bool(os.getenv(env_key, "").strip())
                age_days = 99 if not has_cookie else 0
                status = "unknown" if not has_cookie else "ok"
                last_updated = "Unknown"

            result[platform] = {
                "age_days": age_days,
                "status": status,
                "last_updated": last_updated,
            }

        r.close()
        return JsonResponse({"cookies": result})

    except Exception as e:
        logger.error(f"cookie_status error: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@admin_api
@require_POST
def cookie_update(request):
    """
    Save a new RSSHub cookie from admin panel to Redis.
    The bot reads cookies from Redis on every request — no restart needed.
    Body: { platform: "twitter"|"instagram"|"tiktok", cookie: "auth_token=...; ct0=..." }
    """
    import redis
    from django.conf import settings

    try:
        data = json.loads(request.body)
        platform = data.get("platform", "").lower()
        cookie_value = data.get("cookie", "").strip()

        if platform not in ("twitter", "instagram", "tiktok"):
            return JsonResponse({"error": "Invalid platform"}, status=400)
        if not cookie_value:
            return JsonResponse({"error": "Cookie value is empty"}, status=400)

        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        pipe = r.pipeline()
        # Store cookie for bot to read (no expiry — persists until next update)
        pipe.set(f"rsshub:cookie:{platform}", cookie_value)
        # Store timestamp for age display in admin panel
        pipe.set(f"cookie_updated_at:{platform}", datetime.now(timezone.utc).isoformat())
        pipe.execute()
        r.close()

        logger.info(f"Cookie updated for {platform} by {request.user.username}")
        return JsonResponse({"ok": True, "platform": platform,
                             "message": f"{platform} cookie saved. Takes effect immediately."})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── 2. Celery Queue Size ──────────────────────────────────────────────────────

@admin_api
@require_GET
def celery_queue_stats(request):
    """Return current Celery queue sizes."""
    import redis
    from django.conf import settings

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)

        queues = ["default", "platforms", "ai", "downloads"]
        result = {}
        for q in queues:
            size = r.llen(q)
            result[q] = size

        result["total"] = sum(result.values())

        # Alert threshold: warn if any queue > 500
        result["status"] = "ok"
        for q, size in result.items():
            if isinstance(size, int) and size > 500:
                result["status"] = "warning"
                break
            if isinstance(size, int) and size > 2000:
                result["status"] = "critical"
                break

        r.close()
        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── 3. Revenue Dashboard ──────────────────────────────────────────────────────

@admin_api
@require_GET
def revenue_dashboard(request):
    """Return MRR, churn, revenue history, and subscription breakdown."""
    from .django_models import TransactionProxy, UserProxy

    try:
        now = datetime.now(timezone.utc)
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_30 = now - timedelta(days=30)
        last_7 = now - timedelta(days=7)

        # Revenue this month
        approved = TransactionProxy.objects.filter(
            status="approved",
            reviewed_at__gte=first_of_month,
        )
        revenue_month = sum(float(t.amount_usdt or 0) for t in approved)

        # Revenue last 7 days
        revenue_7d = sum(
            float(t.amount_usdt or 0)
            for t in TransactionProxy.objects.filter(
                status="approved",
                reviewed_at__gte=last_7,
            )
        )

        # Active subscriptions
        active_pro = UserProxy.objects.filter(
            plan="pro",
            subscription_expires_at__gt=now,
        ).count()
        active_premium = UserProxy.objects.filter(
            plan="premium",
            subscription_expires_at__gt=now,
        ).count()

        # MRR estimate
        mrr = (active_pro * 6.0) + (active_premium * 10.0)

        # Users who expired in last 30 days (churned)
        expired = UserProxy.objects.filter(
            subscription_expires_at__gte=last_30,
            subscription_expires_at__lt=now,
            plan="free",
        ).count()

        # Revenue last 30 days per day (for chart)
        daily = {}
        for i in range(30):
            day = (now - timedelta(days=29 - i)).strftime("%m-%d")
            daily[day] = 0

        for t in TransactionProxy.objects.filter(
            status="approved",
            reviewed_at__gte=last_30,
        ):
            if t.reviewed_at:
                day = t.reviewed_at.strftime("%m-%d")
                if day in daily:
                    daily[day] += float(t.amount_usdt or 0)

        # New subscribers this month
        new_subs = TransactionProxy.objects.filter(
            status="approved",
            reviewed_at__gte=first_of_month,
        ).count()

        return JsonResponse({
            "mrr": round(mrr, 2),
            "revenue_month": round(revenue_month, 2),
            "revenue_7d": round(revenue_7d, 2),
            "active_pro": active_pro,
            "active_premium": active_premium,
            "active_total": active_pro + active_premium,
            "new_subs_month": new_subs,
            "churned_30d": expired,
            "daily_revenue": daily,
        })

    except Exception as e:
        logger.error(f"revenue_dashboard error: {e}")
        return JsonResponse({"error": str(e)}, status=500)


# ── 4. Platform Error Rates ───────────────────────────────────────────────────

@admin_api
@require_GET
def platform_error_rates(request):
    """Return fetch success/failure rates per platform from Redis counters."""
    import redis
    from django.conf import settings

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y%m%d%H")
        day_key = now.strftime("%Y%m%d")

        platforms = [
            "youtube", "twitter", "instagram", "tiktok",
            "reddit", "rss", "telegram", "linkedin",
            "threads", "bluesky", "mastodon", "facebook", "discord",
        ]

        result = {}
        for p in platforms:
            success_h = int(r.get(f"fetch:success:{p}:{hour_key}") or 0)
            fail_h    = int(r.get(f"fetch:fail:{p}:{hour_key}") or 0)
            success_d = int(r.get(f"fetch:success:{p}:{day_key}") or 0)
            fail_d    = int(r.get(f"fetch:fail:{p}:{day_key}") or 0)

            total_h = success_h + fail_h
            total_d = success_d + fail_d

            error_rate_h = round((fail_h / total_h * 100), 1) if total_h > 0 else 0
            error_rate_d = round((fail_d / total_d * 100), 1) if total_d > 0 else 0

            status = "ok"
            if error_rate_h > 50:
                status = "critical"
            elif error_rate_h > 20:
                status = "warning"

            result[p] = {
                "error_rate_1h": error_rate_h,
                "error_rate_24h": error_rate_d,
                "total_1h": total_h,
                "total_24h": total_d,
                "failed_1h": fail_h,
                "status": status,
            }

        r.close()
        return JsonResponse({"platforms": result})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── 5. Payment Retry ──────────────────────────────────────────────────────────

@admin_api
@require_POST
def payment_retry(request, tx_id: int):
    """Manually retry a stuck pending transaction."""
    from .django_models import TransactionProxy

    try:
        tx = TransactionProxy.objects.get(pk=tx_id)

        if tx.status not in ("pending", "rejected"):
            return JsonResponse({
                "error": f"Cannot retry transaction with status '{tx.status}'"
            }, status=400)

        # Reset to pending
        tx.status = "pending"
        tx.reject_reason = None
        tx.save(update_fields=["status", "reject_reason"])

        # Fire Celery task
        from worker.tasks import monitor_payment_task
        monitor_payment_task.apply_async(args=[tx_id], countdown=5)

        logger.info(f"Payment retry triggered for tx_id={tx_id} by admin")
        return JsonResponse({"ok": True, "tx_id": tx_id, "message": "Retry queued"})

    except TransactionProxy.DoesNotExist:
        return JsonResponse({"error": "Transaction not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── 6. Manual Subscription Management ────────────────────────────────────────

@admin_api
@require_POST
def subscription_manage(request, user_id: int):
    """
    Manually grant, change, or revoke a user subscription.
    Body: { action: 'grant'|'revoke'|'extend', plan: 'pro'|'premium', days: 30 }
    """
    from .django_models import UserProxy

    try:
        data = json.loads(request.body)
        action = data.get("action")
        plan = data.get("plan", "pro")
        days = int(data.get("days", 30))

        user = UserProxy.objects.get(pk=user_id)
        now = datetime.now(timezone.utc)

        if action == "grant":
            user.plan = plan
            user.subscription_expires_at = now + timedelta(days=days)
            user.save(update_fields=["plan", "subscription_expires_at"])
            msg = f"Granted {plan} for {days} days"

        elif action == "extend":
            base = user.subscription_expires_at or now
            if base < now:
                base = now
            user.subscription_expires_at = base + timedelta(days=days)
            user.save(update_fields=["subscription_expires_at"])
            msg = f"Extended subscription by {days} days"

        elif action == "revoke":
            user.plan = "free"
            user.subscription_expires_at = None
            user.save(update_fields=["plan", "subscription_expires_at"])
            msg = "Subscription revoked — user moved to Free"

        else:
            return JsonResponse({"error": "Invalid action"}, status=400)

        # Notify user via Telegram
        _notify_subscription_change(user.telegram_id, action, plan, user.language)

        logger.info(
            f"Manual subscription: user={user.telegram_id} "
            f"action={action} plan={plan} by={request.user.username}"
        )
        return JsonResponse({"ok": True, "message": msg})

    except UserProxy.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def _notify_subscription_change(telegram_id, action, plan, lang):
    """Send Telegram notification after manual subscription change."""
    try:
        import asyncio
        from bot.utils.telegram_utils import safe_send_message

        msgs = {
            "grant":  f"Your subscription has been updated to <b>{plan.capitalize()}</b> by the admin team.",
            "extend": f"Your <b>{plan.capitalize()}</b> subscription has been extended.",
            "revoke": "Your subscription has been removed. You are now on the Free plan.",
        }
        msg = msgs.get(action, "Your subscription has been updated.")

        async def _send():
            await safe_send_message(telegram_id, msg, parse_mode="HTML")

        asyncio.run(_send())
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id}: {e}")


# ── 7. System Banner ──────────────────────────────────────────────────────────

@admin_api
def system_banner(request):
    """GET: return active banner. POST: set new banner. DELETE: clear banner."""
    import redis
    from django.conf import settings

    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    BANNER_KEY = "system:banner"

    try:
        if request.method == "GET":
            raw = r.get(BANNER_KEY)
            if raw:
                return JsonResponse({"banner": json.loads(raw)})
            return JsonResponse({"banner": None})

        elif request.method == "POST":
            data = json.loads(request.body)
            banner = {
                "message": data.get("message", ""),
                "type": data.get("type", "info"),  # info | warning | critical
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": request.user.username,
            }
            r.set(BANNER_KEY, json.dumps(banner))
            logger.info(f"System banner set by {request.user.username}: {banner['message'][:50]}")
            return JsonResponse({"ok": True, "banner": banner})

        elif request.method == "DELETE":
            r.delete(BANNER_KEY)
            return JsonResponse({"ok": True, "cleared": True})

        return JsonResponse({"error": "Method not allowed"}, status=405)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        r.close()


# ── 8. User Export ────────────────────────────────────────────────────────────

@admin_api
@require_GET
def export_users(request):
    """Export users as CSV or JSON. Format: ?format=csv|json&plan=all|free|pro|premium"""
    from .django_models import UserProxy

    fmt = request.GET.get("format", "csv")
    plan = request.GET.get("plan", "all")
    limit = int(request.GET.get("limit", 10000))

    qs = UserProxy.objects.all().order_by("-created_at")[:limit]
    if plan != "all":
        qs = UserProxy.objects.filter(plan=plan).order_by("-created_at")[:limit]

    fields = [
        "id", "telegram_id", "username", "plan",
        "language", "subscription_expires_at",
        "is_banned", "created_at", "last_active_at",
    ]

    if fmt == "json":
        data = []
        for u in qs:
            row = {}
            for f in fields:
                val = getattr(u, f, None)
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                row[f] = val
            data.append(row)
        response = HttpResponse(
            json.dumps(data, indent=2, default=str),
            content_type="application/json",
        )
        response["Content-Disposition"] = f'attachment; filename="aisocialfeed_users_{datetime.now().strftime("%Y%m%d")}.json"'
        return response

    else:  # CSV
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for u in qs:
            row = {}
            for f in fields:
                val = getattr(u, f, None)
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                row[f] = val
            writer.writerow(row)

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="aisocialfeed_users_{datetime.now().strftime("%Y%m%d")}.csv"'
        return response


# ── 9. Webhook Monitor ────────────────────────────────────────────────────────

@admin_api
@require_GET
def webhook_stats(request):
    """Return Telegram webhook success/failure stats from Redis."""
    import redis
    from django.conf import settings

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        now = datetime.now(timezone.utc)

        stats = {}
        for period, key_fmt in [("1h", "%Y%m%d%H"), ("24h", "%Y%m%d")]:
            key = now.strftime(key_fmt)
            success = int(r.get(f"webhook:success:{key}") or 0)
            fail    = int(r.get(f"webhook:fail:{key}") or 0)
            total   = success + fail
            stats[period] = {
                "success": success,
                "fail": fail,
                "total": total,
                "rate": round((success / total * 100), 1) if total > 0 else 100.0,
            }

        # Last 24 hours hourly breakdown for chart
        hourly = []
        for i in range(24):
            hour = now - timedelta(hours=23 - i)
            k = hour.strftime("%Y%m%d%H")
            s = int(r.get(f"webhook:success:{k}") or 0)
            f_ = int(r.get(f"webhook:fail:{k}") or 0)
            hourly.append({
                "hour": hour.strftime("%H:00"),
                "success": s,
                "fail": f_,
            })

        r.close()
        return JsonResponse({"stats": stats, "hourly": hourly})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── 10. User Map (Country Distribution) ──────────────────────────────────────

@admin_api
@require_GET
def user_map(request):
    """Return user count per country inferred from language setting."""
    from .django_models import UserProxy
    from django.db.models import Count

    # Map language codes to country names
    LANG_TO_COUNTRY = {
        "fa": "Iran",
        "ar": "Saudi Arabia / Arabic",
        "ru": "Russia",
        "en": "United States / English",
        "zh": "China",
        "tr": "Turkey",
        "hi": "India",
        "de": "Germany",
        "fr": "France",
        "es": "Spain / Latin America",
        "pt": "Brazil / Portugal",
        "ja": "Japan",
        "ko": "Korea",
        "uk": "Ukraine",
        "ur": "Pakistan",
        "bn": "Bangladesh",
        "ku": "Kurdistan",
    }

    try:
        lang_counts = (
            UserProxy.objects.values("language")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        result = []
        for row in lang_counts:
            lang = row["language"] or "en"
            result.append({
                "language": lang,
                "country": LANG_TO_COUNTRY.get(lang, lang.upper()),
                "count": row["count"],
            })

        total = sum(r["count"] for r in result)
        for r in result:
            r["percent"] = round(r["count"] / total * 100, 1) if total > 0 else 0

        return JsonResponse({"countries": result, "total": total})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
