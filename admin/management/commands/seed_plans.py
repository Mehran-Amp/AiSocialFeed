"""
SocialtoFeed — Seed Plans
Prices verified against aisocialfeed.com/en/ — May 2026
Run: python manage.py seed_plans
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed plan configurations from DEFAULT_PLAN_FEATURES"

    def handle(self, *args, **options):
        from config.settings import DEFAULT_PLAN_FEATURES
        from admin.django_models import PlanConfigProxy as PlanConfig, SystemConfigProxy as SystemConfig
        from django.db import connection

        self.stdout.write("Seeding plan configurations...")

        plans_data = [
            {
                "plan": "free",
                "display_name": "Free",
                "max_accounts": 5,
                "max_categories": 3,
                "bookmark_limit": 0,   # v3.3: unlimited
                "ticket_limit": 1,
                "ai_enabled": False,
                "ai_daily_limit": 0,
                "digest_enabled": False,
                "email_digest": False,
                "channel_forward": False,
                "export_csv": False,
                "export_json": False,
                "fetch_on_demand": False,
                "stream_video": True,
                "download_link": False,
                "download_link_qualities": [],
                "download_file": False,
                "audio_link": False,
                "audio_file": False,
                "fetch_interval_options": [60],
                "upsell_every_n_posts": 50,
                "early_access": False,
                "priority_support": False,
                "price_monthly": 0.0,
                "price_biannual": 0.0,
                "price_yearly": 0.0,
            },
            {
                "plan": "pro",
                "display_name": "Pro",
                "max_accounts": 40,
                "max_categories": 10,
                "bookmark_limit": 0,   # v3.3: unlimited
                "ticket_limit": 2,
                "ai_enabled": False,
                "ai_daily_limit": 0,
                "digest_enabled": False,
                "email_digest": False,
                "channel_forward": True,
                "export_csv": True,
                "export_json": False,
                "fetch_on_demand": False,
                "stream_video": True,
                "download_link": True,
                "download_link_qualities": ["480p", "720p"],
                "download_file": False,
                "audio_link": True,
                "audio_file": False,
                "fetch_interval_options": [30],
                "upsell_every_n_posts": 200,
                "early_access": False,
                "priority_support": False,
                # CORRECT prices per aisocialfeed.com
                "price_monthly": 6.0,
                "price_biannual": 28.8,
                "price_yearly": 57.6,
            },
            {
                "plan": "premium",
                "display_name": "Premium",
                "max_accounts": 100,
                "max_categories": 20,
                "bookmark_limit": 0,   # v3.3: unlimited
                "ticket_limit": 3,
                "ai_enabled": True,
                "ai_daily_limit": 0,  # unlimited
                "digest_enabled": True,
                "email_digest": True,
                "channel_forward": True,
                "export_csv": True,
                "export_json": True,
                "fetch_on_demand": True,
                "stream_video": True,
                "download_link": True,
                "download_link_qualities": ["480p", "720p", "1080p"],
                "download_file": True,
                "audio_link": True,
                "audio_file": True,
                "fetch_interval_options": [5, 15, 30, 60],
                "upsell_every_n_posts": 0,
                "early_access": True,
                "priority_support": True,
                # CORRECT prices per aisocialfeed.com
                "price_monthly": 10.0,
                "price_biannual": 48.0,
                "price_yearly": 96.0,
            },
        ]

        for plan_data in plans_data:
            plan_name = plan_data.pop("plan")
            try:
                obj, created = PlanConfig.objects.update_or_create(
                    plan=plan_name,
                    defaults=plan_data,
                )
                action = "Created" if created else "Updated"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {action} plan: {plan_name} "
                        f"(${plan_data.get('price_monthly', 0)}/mo)"
                    )
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Failed to seed {plan_name}: {e}"))

        # System configs
        system_configs = [
            {"key": "maintenance_mode", "value": "false"},
            {"key": "nowpayments_enabled", "value": "false"},
            {"key": "referral_bonus_accounts", "value": "2"},
            {"key": "max_referral_bonus", "value": "10"},
            {"key": "registration_open", "value": "true"},
            {"key": "ai_global_enabled", "value": "true"},
        ]

        for sc in system_configs:
            try:
                SystemConfig.objects.get_or_create(
                    key=sc["key"],
                    defaults={"value": sc["value"]},
                )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  SystemConfig {sc['key']}: {e}"))

        self.stdout.write(self.style.SUCCESS("\n✅ Plan seeding complete!"))
        self.stdout.write("  Free: $0 | Pro: $6/mo $57.60/yr | Premium: $10/mo $96/yr")
        self.stdout.write("\nNext steps:")
        self.stdout.write("  1. python manage.py migrate")
        self.stdout.write("  2. python manage.py createsuperuser")
        self.stdout.write("  3. Go to Admin → Plan Configs to verify")
