from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

import admin.admin_config as _admin_config  # noqa: F401

from admin.api import (
    cookie_status, cookie_update,
    celery_queue_stats,
    revenue_dashboard,
    platform_error_rates,
    payment_retry,
    subscription_manage,
    system_banner,
    export_users,
    webhook_stats,
    user_map,
)


# Fix 5: Serve the custom admin_panel.html at /panel/
@staff_member_required
def custom_panel(request):
    """Serve the custom-designed admin panel HTML."""
    return render(request, "admin_panel.html")


urlpatterns = [
    path("admin/", admin.site.urls),

    # Custom admin panel (your designed HTML)
    path("panel/", custom_panel, name="custom_panel"),

    # API endpoints
    path("api/cookies/",              cookie_status,        name="api_cookie_status"),
    path("api/cookies/update/",       cookie_update,        name="api_cookie_update"),
    path("api/celery/queues/",        celery_queue_stats,   name="api_celery_queues"),
    path("api/revenue/",              revenue_dashboard,    name="api_revenue"),
    path("api/platforms/errors/",     platform_error_rates, name="api_platform_errors"),
    path("api/payment/<int:tx_id>/retry/", payment_retry,   name="api_payment_retry"),
    path("api/subscription/<int:user_id>/manage/", subscription_manage, name="api_sub_manage"),
    path("api/banner/",               system_banner,        name="api_banner"),
    path("api/users/export/",         export_users,         name="api_users_export"),
    path("api/webhook/stats/",        webhook_stats,        name="api_webhook_stats"),
    path("api/users/map/",            user_map,             name="api_user_map"),
]

urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)