# AiSocialFeed — Changelog

## v3.2 — May 2026

### Critical Bug Fixes
- Added missing `RSSHubConfig` class (bot crashed on import)
- Added missing `nowpayments_enabled` field on PaymentConfig
- Created missing `bot/services/payment_service.py` (payments were 100% broken)
- Added missing `_fetch_rsshub()` and `_parse_entries()` functions in fetchers.py
- Added `FacebookFetcher` and `DiscordFetcher` to PLATFORM_FETCHERS registry
- Fixed missing `aioredis` import in ai_service.py
- Fixed `rsshub` service placed inside `volumes:` block in docker-compose.yml
- Fixed `TransactionMethod.USDT` → `TransactionMethod.CRYPTO` across all files
- Added missing Transaction model fields: deposit_address, network, address_expires_at, address_generated_at
- Added missing PlanConfig model fields: features_json, bookmark_limit, ticket_limit, fetch_on_demand
- Fixed `process_post()` argument mismatch in base.py (AI features were silently broken)
- Fixed `spam_score` → `is_spam` in _format_post (spam tagging never worked)

### Platform & Stability
- Migrated Twitter, Instagram, TikTok, Threads, Facebook, Discord from Nitter/RSSBridge to self-hosted RSSHub
- All platform resolvers updated to use RSSHub
- RSSHub cookies now stored in Redis — update from admin panel without SSH or restart
- `_get_cookie()` reads from Redis first, falls back to .env
- Health checker updated to monitor RSSHub instead of Nitter
- Beat scheduler fixed: `worker.tasks beat` with file-based scheduler

### Performance
- Spread scheduling: 10,000 tasks spread over 25 minutes instead of all at once
- RSSHub cache increased from 5 to 10 minutes (halves outbound requests)
- Dedicated `stf_worker_platforms` container with max concurrency=4 for RSSHub
- Main worker concurrency increased to 6 for AI/downloads/system tasks

### User Experience
- Users notified when their account has consecutive fetch failures (was silent before)
- Admin receives cookie-specific hint when RSSHub platforms fail repeatedly
- Renamed all `socialtofeed` references to `aisocialfeed`
- Seed plan prices corrected to match website: Pro $6, Premium $10

### Admin Panel
- New: Cookie Status page with update form (no SSH needed)
- New: Celery Queue Size monitor
- New: Revenue Dashboard (MRR, churn, daily chart)
- New: Platform Error Rates per platform
- New: Payment Retry button
- New: Manual Subscription Management (grant/extend/revoke)
- New: System Banner management
- New: User Export (CSV / JSON)
- New: Webhook Monitor
- New: User Map (distribution by language)
- Fully mobile responsive with hamburger menu
- Clean typography using Geist font

### New Files
- `bot/services/payment_service.py` — CoinEx API integration
- `admin/api.py` — 11 REST endpoints for admin panel features
- `admin/static/admin_panel.html` — Standalone admin panel UI

### Configuration
- `.env.example` fully updated: all 33 variables documented
- RSSHub cookie variables added
- CoinEx payment variables added
- Django secret key generation instructions added
