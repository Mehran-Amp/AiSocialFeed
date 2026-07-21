# SocialtoFeed — Setup & Deployment Guide

## Overview
Multi-platform social media feed aggregator Telegram bot.
Supports YouTube, Twitter/X, Instagram, RSS, TikTok, LinkedIn, Reddit, Telegram channels.

**Stack:** Python 3.11 · PostgreSQL 16 · Redis 7 · Celery · Django Admin · Docker

---

## Quick Start

### 1. Clone and configure
```bash
git clone <repo>
cd aisocialfeed
cp .env.example .env
nano .env   # fill in required values
```

### 2. Required .env values
```
BOT_TOKEN=           # from @BotFather
ADMIN_TELEGRAM_ID=   # your Telegram user ID
POSTGRES_PASSWORD=   # strong random password
REDIS_PASSWORD=      # strong random password
DJANGO_SECRET_KEY=   # 50+ random chars
ENCRYPTION_KEY=      # 32+ chars for API key encryption
```

### 3. Start
```bash
docker-compose up -d
docker-compose logs -f bot   # watch bot logs
```

### 4. Create admin user
```bash
docker-compose exec admin python manage.py createsuperuser
```

### 5. Seed plan configs
```bash
docker-compose exec admin python manage.py seed_plans
```

Access admin panel: `http://your-server:8000/admin/`

---

## Production (Webhook mode)

Add to .env:
```
WEBHOOK_URL=https://yourdomain.com
```

Then:
```bash
# Point your domain to the server
# Set up nginx reverse proxy to port 8443 (bot) and 8000 (admin)
docker-compose up -d
```

---

## DeepSeek API Key

1. Get API key from [platform.deepseek.com](https://platform.deepseek.com)
2. Set in Admin Panel → System Config → `deepseek_api_key`
3. Or set `DEEPSEEK_API_KEY=sk-xxx` in .env before starting

Models used:
- `deepseek-v4-flash` — translation, categorization, Q&A (fast + cheap)
- `deepseek-v4-pro` — complex summaries (higher quality)

---

## Project Structure

```
aisocialfeed/
├── bot/
│   ├── handlers/       # Telegram command/button handlers
│   ├── platforms/      # Platform fetchers (YouTube, Twitter, etc.)
│   ├── services/       # AI, digest, resolver
│   ├── middlewares/    # Auth, rate limiting
│   └── utils/          # Logger, keyboards, translator
├── worker/
│   └── tasks.py        # All Celery background tasks
├── admin/              # Django admin panel
├── translations/       # 18x JSON language files
├── docker/             # Dockerfile + backup script
├── config/             # Central configuration
└── docker-compose.yml
```

---

## Adding a New Language

1. Copy `translations/en.json` to `translations/XX.json`
2. Translate all values
3. Add the language code and name to `SUPPORTED_LANGUAGES` in `bot/utils/translator.py`
4. Restart the bot: `docker-compose restart bot`

---

## Backup & Restore

Backups run automatically every 24 hours. Location: `./backups/`

Manual backup:
```bash
docker-compose exec db pg_dump -U stfuser aisocialfeed > backup.sql
```

Restore:
```bash
docker-compose exec -T db psql -U stfuser aisocialfeed < backup.sql
```

---

## Debug Report

From Admin Panel → System Logs → Actions → "Export Full Debug Report"

Or direct URL: `/admin/admin/systemlogproxy/full-debug-report/`

The JSON report includes:
- System metrics (CPU, RAM, disk)
- Database stats
- Redis status
- DeepSeek API status
- Recent errors with stack traces
- Platform health

---

## Scaling (when user count grows)

When you reach 500+ users:

1. **Separate Celery queues** — already configured in `worker/tasks.py`
2. **Twitter API** — upgrade from Nitter to official API (`TWITTER_API_KEY=`)
3. **Instagram** — switch to Instagrapi with crawler account
4. **Download server** — move yt-dlp to separate container
5. **DB read replica** — for analytics queries

---

## Troubleshooting

**Bot not responding:**
```bash
docker-compose logs bot --tail=50
```

**Fetch not working:**
```bash
docker-compose logs worker --tail=50
```

**Admin panel not loading:**
```bash
docker-compose logs admin --tail=50
```

**Check Celery queue:**
```bash
docker-compose exec redis redis-cli -a $REDIS_PASSWORD llen celery
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram bot token |
| `ADMIN_TELEGRAM_ID` | ✅ | Your Telegram ID for alerts |
| `POSTGRES_PASSWORD` | ✅ | Database password |
| `REDIS_PASSWORD` | ✅ | Redis password |
| `DJANGO_SECRET_KEY` | ✅ | Django secret key |
| `ENCRYPTION_KEY` | ✅ | For encrypting API keys in DB |
| `DEEPSEEK_API_KEY` | ⚠️ | Required for AI features |
| `WEBHOOK_URL` | ⚠️ | For production webhook mode |
| `NOWPAYMENTS_API_KEY` | ❌ | Mastercard payments (future) |
| `LOG_LEVEL` | ❌ | DEBUG/INFO/WARNING (default: INFO) |
