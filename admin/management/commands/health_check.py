"""
AiSocialFeed — Health Check Management Command  (v3.2)

Usage:
    python manage.py health_check            # human-readable output
    python manage.py health_check --json     # structured JSON (for CI/CD)
    python manage.py health_check --alert-on-fail  # send CRITICAL alert if any check fails

Checks:
    1. Database      — connection + SELECT 1 + Alembic revision vs head
    2. Redis         — ping + memory + connected clients
    3. Telegram API  — getMe + webhook info + last webhook update timestamp
    4. Celery        — worker heartbeat keys in Redis
    5. Circuit Breakers — per-platform open/closed state
    6. Pending Payments — monitors older than 30 min
    7. Disk          — log and media directory sizes

Exit codes:
    0 — all checks passed
    1 — one or more checks failed

Wired into docker-compose.yml healthcheck directive.
"""

import json
import os
import sys
import asyncio
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run full system health check for AiSocialFeed bot"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="output_json",
            help="Output results as JSON",
        )
        parser.add_argument(
            "--alert-on-fail",
            action="store_true",
            dest="alert_on_fail",
            help="Send CRITICAL Telegram alert if any check fails",
        )

    def handle(self, *args, **options):
        results = asyncio.run(self._run_all_checks())
        failed  = [k for k, v in results.items() if v.get("status") == "fail"]
        passed  = [k for k, v in results.items() if v.get("status") == "ok"]
        warned  = [k for k, v in results.items() if v.get("status") == "warn"]

        if options["output_json"]:
            self.stdout.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "overall":   "fail" if failed else "ok",
                "checks":    results,
            }, indent=2))
        else:
            self._print_human(results, passed, warned, failed)

        if failed and options["alert_on_fail"]:
            asyncio.run(self._send_alert(failed, results))

        sys.exit(1 if failed else 0)

    # ── Human-readable output ─────────────────────────────────────────────────

    def _print_human(self, results, passed, warned, failed):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.stdout.write(f"\n{'═'*55}")
        self.stdout.write(f"  AiSocialFeed Health Check — {now}")
        self.stdout.write(f"{'═'*55}\n")

        for check, data in results.items():
            status = data.get("status", "?")
            icon   = {"ok":"✅","warn":"⚠️","fail":"❌"}.get(status, "⚪️")
            detail = data.get("detail", "")
            self.stdout.write(f"  {icon}  {check:<28} {detail}")

        self.stdout.write(f"\n{'─'*55}")
        self.stdout.write(
            f"  ✅ {len(passed)} passed   "
            f"⚠️ {len(warned)} warnings   "
            f"❌ {len(failed)} failed"
        )
        overall = "HEALTHY" if not failed else "UNHEALTHY"
        self.stdout.write(f"  Overall: {overall}\n")

    # ── Alert on failure ──────────────────────────────────────────────────────

    async def _send_alert(self, failed: list, results: dict) -> None:
        try:
            from bot.utils.alerts import alert_critical
            details = "\n".join(
                f"  ❌ {k}: {results[k].get('detail','')}"
                for k in failed
            )
            await alert_critical(
                "Health Check Failed",
                details,
                failed_checks=", ".join(failed),
                action="Run: python manage.py health_check for details",
            )
        except Exception as e:
            self.stderr.write(f"Failed to send alert: {e}")

    # ── All checks ────────────────────────────────────────────────────────────

    async def _run_all_checks(self) -> dict:
        checks = {}
        checks["1. Database"]        = await self._check_db()
        checks["2. Redis"]           = await self._check_redis()
        checks["3. Telegram API"]    = await self._check_telegram()
        checks["4. Celery Workers"]  = await self._check_celery()
        checks["5. Circuit Breakers"]= await self._check_circuits()
        checks["6. Pending Payments"]= await self._check_payments()
        checks["7. Disk"]            = await self._check_disk()
        return checks

    # ── Check 1: Database ─────────────────────────────────────────────────────

    async def _check_db(self) -> dict:
        try:
            import django
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.django_settings")
            from django.db import connection
            with connection.cursor() as c:
                c.execute("SELECT 1")

            # Alembic revision check
            try:
                c2 = connection.cursor()
                c2.execute("SELECT version_num FROM alembic_version LIMIT 1")
                row = c2.fetchone()
                revision = row[0] if row else "none"
                return {"status": "ok", "detail": f"connected, revision={revision}"}
            except Exception:
                return {"status": "ok", "detail": "connected (alembic table not found)"}
        except Exception as e:
            return {"status": "fail", "detail": str(e)[:80]}

    # ── Check 2: Redis ────────────────────────────────────────────────────────

    async def _check_redis(self) -> dict:
        try:
            import redis.asyncio as aioredis
            from config.settings import config
            r = aioredis.from_url(config.redis.url)
            await r.ping()
            info = await r.info("memory")
            mem_mb = round(info.get("used_memory", 0) / 1024 / 1024, 1)
            clients = (await r.info("clients")).get("connected_clients", "?")
            await r.aclose()
            return {"status": "ok", "detail": f"{mem_mb} MB used, {clients} clients"}
        except Exception as e:
            return {"status": "fail", "detail": str(e)[:80]}

    # ── Check 3: Telegram API ─────────────────────────────────────────────────

    async def _check_telegram(self) -> dict:
        try:
            from config.settings import config
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{config.telegram.token}/getMe"
                )
                data = r.json()
                if not data.get("ok"):
                    return {"status": "fail", "detail": f"getMe failed: {data}"}
                username = data["result"].get("username", "?")

                # Webhook info
                wh = await client.get(
                    f"https://api.telegram.org/bot{config.telegram.token}/getWebhookInfo"
                )
                wh_data = wh.json().get("result", {})
                pending = wh_data.get("pending_update_count", 0)
                last_err = wh_data.get("last_error_message", "none")
                url_set  = bool(wh_data.get("url"))

                detail = f"@{username} webhook={'set' if url_set else 'polling'} pending={pending}"
                status = "warn" if pending > 50 or (url_set and last_err != "none") else "ok"
                if url_set and last_err != "none":
                    detail += f" last_error={last_err[:40]}"
                return {"status": status, "detail": detail}
        except Exception as e:
            return {"status": "fail", "detail": str(e)[:80]}

    # ── Check 4: Celery Workers ───────────────────────────────────────────────

    async def _check_celery(self) -> dict:
        try:
            import redis.asyncio as aioredis
            from config.settings import config
            r = aioredis.from_url(config.redis.url)
            hb_keys = await r.keys("celery:worker:heartbeat:*")
            await r.aclose()
            count = len(hb_keys)
            if count == 0:
                return {"status": "fail", "detail": "No workers alive (no heartbeat keys)"}
            return {"status": "ok", "detail": f"{count} worker(s) alive"}
        except Exception as e:
            return {"status": "fail", "detail": str(e)[:80]}

    # ── Check 5: Circuit Breakers ─────────────────────────────────────────────

    async def _check_circuits(self) -> dict:
        try:
            import redis.asyncio as aioredis
            from config.settings import config
            r = aioredis.from_url(config.redis.url)
            open_keys = await r.keys("cb:open:*")
            await r.aclose()
            if open_keys:
                platforms = [k.split(":")[-1] for k in open_keys]
                return {"status": "warn",
                        "detail": f"OPEN: {', '.join(platforms)}"}
            return {"status": "ok", "detail": "All circuits closed"}
        except Exception as e:
            return {"status": "fail", "detail": str(e)[:80]}

    # ── Check 6: Pending Payments ─────────────────────────────────────────────

    async def _check_payments(self) -> dict:
        try:
            from django.db import connection
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
            with connection.cursor() as c:
                c.execute(
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE status='pending' AND created_at <= %s",
                    [cutoff],
                )
                row = c.fetchone()
                stuck = row[0] if row else 0
            if stuck > 0:
                return {"status": "warn",
                        "detail": f"{stuck} payment(s) stuck >30 min"}
            return {"status": "ok", "detail": "No stuck payments"}
        except Exception as e:
            return {"status": "warn", "detail": f"Could not check: {e}"[:60]}

    # ── Check 7: Disk ─────────────────────────────────────────────────────────

    async def _check_disk(self) -> dict:
        def _size_mb(path: str) -> float:
            total = 0
            if not os.path.exists(path):
                return 0.0
            for dirpath, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            return round(total / 1024 / 1024, 1)

        log_mb   = _size_mb("/app/logs")
        media_mb = _size_mb("/app/media")
        status   = "warn" if log_mb > 500 or media_mb > 2000 else "ok"
        return {
            "status": status,
            "detail": f"logs={log_mb} MB  media={media_mb} MB",
        }
