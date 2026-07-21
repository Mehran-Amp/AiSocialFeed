"""
SocialtoFeed — Admin Broadcast Panel
Rate-limited broadcast via Celery (1 msg/sec, safe from Telegram flood bans).
Also includes screenshot viewer endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from django.contrib import admin, messages
from django.http import HttpResponse
from django.urls import path

logger = logging.getLogger(__name__)


class BroadcastAdminMixin:
    """
    Mixin to add broadcast functionality to any admin class.
    Uses Celery task for rate-limited delivery (1/sec).
    """

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "broadcast/",
                self.admin_site.admin_view(self.broadcast_view),
                name="broadcast",
            ),
            path(
                "screenshot/<int:tx_id>/",
                self.admin_site.admin_view(self.screenshot_view),
                name="screenshot_view",
            ),
        ]
        return custom + urls

    def broadcast_view(self, request):
        """Simple broadcast form — POST sends via Celery task."""
        from django.shortcuts import render

        if request.method == "POST":
            message = request.POST.get("message", "").strip()
            plan_filter = request.POST.get("plan_filter", "all")

            if not message:
                messages.error(request, "Message cannot be empty.")
            else:
                from worker.growth import broadcast_message_task
                task = broadcast_message_task.delay(message, plan_filter)
                messages.success(
                    request,
                    f"Broadcast queued (task ID: {task.id}). "
                    f"Sending to '{plan_filter}' users at 1 msg/sec."
                )

        context = {
            "title": "Broadcast Message",
            "plan_choices": [("all", "All Users"), ("pro", "Pro Only"), ("premium", "Premium Only")],
        }
        return render(request, "admin/broadcast.html", context)

    def screenshot_view(self, request, tx_id: int):
        """
        Retrieves and serves a payment screenshot stored as Telegram file_id.
        Proxies the file from Telegram servers to admin browser.
        """
        from admin.django_models import TransactionProxy

        if not request.user.is_staff:
            return HttpResponse("Forbidden", status=403)

        try:
            tx = TransactionProxy.objects.get(pk=tx_id)
        except TransactionProxy.DoesNotExist:
            return HttpResponse("Transaction not found", status=404)

        screenshot_path = tx.screenshot_path
        if not screenshot_path:
            return HttpResponse("No screenshot for this transaction", status=404)

        if not screenshot_path.startswith("tg:"):
            # Local file path
            try:
                with open(screenshot_path, "rb") as f:
                    return HttpResponse(f.read(), content_type="image/jpeg")
            except FileNotFoundError:
                return HttpResponse("File not found", status=404)

        # Telegram file_id — fetch from Telegram
        file_id = screenshot_path[3:]  # strip "tg:"

        async def _fetch():
            from bot.utils.telegram_utils import get_bot
            bot = get_bot()
            file = await bot.get_file(file_id)
            # Download file bytes
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(file.file_path)
                return resp.content, resp.headers.get("content-type", "image/jpeg")

        try:
            loop = asyncio.new_event_loop()
            content, content_type = loop.run_until_complete(_fetch())
            loop.close()
            return HttpResponse(content, content_type=content_type)
        except Exception as e:
            logger.error(f"Screenshot fetch failed for tx {tx_id}: {e}")
            return HttpResponse(f"Could not retrieve screenshot: {e}", status=500)
