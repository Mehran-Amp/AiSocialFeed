# SocialtoFeed v3.2 - Developer Guide
## Complete Setup, Operations, Troubleshooting and Zero-Downtime Upgrade Guide

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [VPS Requirements](#2-vps-requirements)
3. [First-Time Setup](#3-first-time-setup)
4. [Environment Configuration](#4-environment-configuration)
5. [First Deployment](#5-first-deployment)
6. [Nginx and SSL Setup](#6-nginx-and-ssl-setup)
7. [Scheduled Tasks Reference](#7-scheduled-tasks-reference)
8. [Zero-Downtime Updates](#8-zero-downtime-updates)
9. [Database Migrations](#9-database-migrations)
10. [RSSHub Cookie Refresh](#10-rsshub-cookie-refresh)
11. [Backup and Recovery](#11-backup-and-recovery)
12. [Monitoring and Logs](#12-monitoring-and-logs)
13. [Troubleshooting Guide](#13-troubleshooting-guide)
14. [Security Hardening](#14-security-hardening)
15. [Scaling Guide](#15-scaling-guide)
16. [Quick Reference Card](#16-quick-reference-card)

---

## 1. Architecture Overview

The project runs as 8 Docker containers on a single VPS:

| Container | Role |
|---|---|
| stf_bot | Telegram bot process (python-telegram-bot, async) |
| stf_worker | Celery worker - fetches feeds, sends posts, AI, downloads |
| stf_beat | Celery beat scheduler - fires tasks on schedule |
| stf_admin | Django admin panel on port 8000 (Gunicorn, 2 workers) |
| stf_db | PostgreSQL 16 - main database with persistent volume |
| stf_redis | Redis 7 - session cache, Celery broker, RSSHub cache |
| stf_rsshub | Self-hosted RSSHub - serves Twitter/Instagram/TikTok/Threads/Facebook/Discord |
| stf_backup | Runs pg_dump daily at 3AM - keeps last 7 backups |

**Redis database layout:**

| DB Number | Usage |
|---|---|
| DB 0 | Bot sessions and cache |
| DB 1 | Celery broker (task queue) |
| DB 2 | Celery results |
| DB 3 | RSSHub cache |

---

## 2. VPS Requirements

### Minimum specs to launch (0 to 200 users)

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 2 vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB SSD | 40 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

NOTE: Best value is Hetzner CX22 - 2 vCPU, 4 GB RAM, 40 GB SSD - approximately 4.5 EUR per month.

### Growth path

| Users | CPU and RAM | Hetzner Model | Cost |
|---|---|---|---|
| 0 to 200 | 2 vCPU / 4 GB | CX22 | ~5 EUR/mo |
| 200 to 1,000 | 4 vCPU / 8 GB | CX32 | ~14 EUR/mo |
| 1,000 to 5,000 | 8 vCPU / 16 GB | CX42 | ~30 EUR/mo |
| 5,000 and above | Split services | Multiple servers | - |

IMPORTANT: Always scale RAM before CPU. The bot and RSSHub together use about 2 GB RAM at 500 users.

---

## 3. First-Time Setup

### Step 3.1 - Connect and prepare the VPS

```bash
# Connect as root
ssh root@YOUR_VPS_IP

# Update system packages
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
apt install -y docker-compose-plugin

# Verify versions
docker --version
docker compose version

# Install useful tools
apt install -y git curl wget htop ufw fail2ban nginx certbot python3-certbot-nginx
```

### Step 3.2 - Create a dedicated app user

```bash
# Never run the bot as root
useradd -m -s /bin/bash stf
usermod -aG docker stf

# Switch to app user
su - stf
```

### Step 3.3 - Upload project files

```bash
# Option A: Upload zip from your local machine
scp stf_v32_final.zip stf@YOUR_VPS_IP:/home/stf/

# On the VPS
su - stf
unzip stf_v32_final.zip
mv stf_v31_fixed socialtofeed
cd socialtofeed

# Option B: Git clone
git clone https://github.com/youruser/socialtofeed.git
cd socialtofeed
```

### Step 3.4 - Generate required secret keys

```bash
# Generate Django secret key
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# Copy this output for DJANGO_SECRET_KEY

# Generate Fernet encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copy this output for ENCRYPTION_KEY
```

---

## 4. Environment Configuration

### Step 4.1 - Create .env from the template

```bash
cd /home/stf/socialtofeed
cp .env.example .env
nano .env
```

### Step 4.2 - Fill in every required value

```bash
# Telegram
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_TELEGRAM_ID=your_telegram_user_id
BOT_USERNAME=AiSocialFeedBot

# v3.2: Admin alert channel (create a private channel, add bot as admin, paste ID here)
# Get channel ID: forward any channel message to @userinfobot
ADMIN_CHANNEL_ID=-100xxxxxxxxxx
# Suppress the same alert type for N seconds (default: 300 = 5 min)
ALERT_RATE_LIMIT_SECONDS=300
# Digest interval in hours sent to admin channel (default: 6)
DIGEST_INTERVAL_HOURS=6

# v3.7: Proxy for Telegram API — required in Iran, China, and other restricted regions
# Formats: socks5://user:pass@host:port  |  http://host:port  |  socks5h://host:port
# Leave blank if Telegram is directly accessible from your server
HTTPS_PROXY=

# PostgreSQL - choose a strong password
POSTGRES_PASSWORD=strong_random_password
DATABASE_URL=postgresql+asyncpg://stfuser:strong_random_password@db:5432/socialtofeed

# Redis - choose a strong password
REDIS_PASSWORD=strong_random_password
REDIS_URL=redis://:strong_random_password@redis:6379/0
CELERY_BROKER_URL=redis://:strong_random_password@redis:6379/1
CELERY_RESULT_BACKEND=redis://:strong_random_password@redis:6379/2

# Django
DJANGO_SECRET_KEY=paste_generated_key_here
ENCRYPTION_KEY=paste_generated_key_here
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,aisocialfeed.com

# DeepSeek AI
DEEPSEEK_API_KEY=your_deepseek_api_key

# CoinEx Payments
COINEX_ACCESS_ID=your_coinex_access_id
COINEX_SECRET_KEY=your_coinex_secret_key

# RSSHub - leave cookies blank now, add them later
RSSHUB_URL=http://rsshub:1200
RSSHUB_COOKIE_TWITTER=
RSSHUB_COOKIE_INSTAGRAM=
RSSHUB_COOKIE_TIKTOK=
```

### Step 4.3 - Secure the .env file

```bash
# Only the app user can read this file
chmod 600 .env
```

---

## 5. First Deployment

### Step 5.1 - Start infrastructure first

```bash
cd /home/stf/socialtofeed

# Start only database and Redis
docker compose up -d db redis

# Wait 20 seconds then verify both are healthy
docker compose ps
# Both stf_db and stf_redis must show: healthy
```

### Step 5.2 - Run database migrations

```bash
docker compose run --rm bot python -m alembic upgrade head
# Expected output: Running upgrade -> 001_initial, OK
```

### Step 5.3 - Set up Django admin

```bash
# Run Django migrations
docker compose run --rm admin python manage.py migrate --noinput

# Seed plan configurations with correct prices
docker compose run --rm admin python manage.py seed_plans

# Create your admin superuser account
docker compose run --rm admin python manage.py createsuperuser

# Collect static files
docker compose run --rm admin python manage.py collectstatic --noinput
```

### Step 5.4 - Start all services

```bash
docker compose up -d

# Verify all 8 containers are running
docker compose ps
```

Expected result:

| Container | Status |
|---|---|
| stf_bot | Up (healthy) |
| stf_worker | Up |
| stf_beat | Up |
| stf_admin | Up - port 8000 |
| stf_db | Up (healthy) |
| stf_redis | Up (healthy) |
| stf_rsshub | Up (healthy) |
| stf_backup | Up |

### Step 5.5 - Test the bot

```bash
# Send /start to your bot on Telegram
# Then check logs
docker compose logs -f bot
# Should show: Bot started polling  OR  Webhook set
```

### Step 5.6 - Set up webhook (production only)

After SSL is configured in section 6:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://aisocialfeed.com/webhook"

# Then add to .env
WEBHOOK_URL=https://aisocialfeed.com/webhook

# Restart bot
docker compose restart bot
```

---

## 6. Nginx and SSL Setup

### Step 6.1 - Configure Nginx

```bash
nano /etc/nginx/sites-available/aisocialfeed.com
```

```nginx
server {
    listen 80;
    server_name aisocialfeed.com www.aisocialfeed.com;

    root /var/www/html;
    index index.html;

    location = / {
        return 301 /en/;
    }

    location / {
        try_files $uri $uri/ =404;
    }

    location /webhook {
        proxy_pass http://localhost:8443;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name admin.aisocialfeed.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Restrict to your IP only
        allow YOUR_IP_ADDRESS;
        deny all;
    }
}
```

```bash
# Upload website files
cp /path/to/website/files /var/www/html/

# Enable and test
ln -s /etc/nginx/sites-available/aisocialfeed.com /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

### Step 6.2 - Get free SSL certificate

```bash
certbot --nginx -d aisocialfeed.com -d www.aisocialfeed.com -d admin.aisocialfeed.com
# Select: redirect all HTTP to HTTPS

# Test auto-renewal
certbot renew --dry-run
```

---

## 7. Scheduled Tasks Reference

All tasks run automatically via stf_beat and are defined in worker/tasks.py.

| Task Name | Schedule | What It Does |
|---|---|---|
| schedule_pending_fetches | Every 15 min | Queues feed fetch jobs for all active accounts |
| check_subscriptions | Every hour | Detects expired subscriptions, applies 48h grace period |
| send_due_digests | Every hour | Sends daily AI digest to Premium users |
| send_expiry_warnings | Daily 9 AM | Warns users expiring in 7, 3, or 1 days |
| cleanup_old_posts | Sunday 3 AM | Deletes sent posts older than 90 days |
| check_platform_health | Every 15 min | Checks RSSHub health, alerts admin if down |
| check_rsshub_health | Every 15 min | Dedicated RSSHub ping check |
| reengage_inactive | Daily 11 AM | Nudges users with 0 accounts after 3 days |
| send_growth_report | Daily 3 AM | Sends daily stats summary to admin Telegram |

### Manually trigger any task

```bash
docker compose exec worker celery -A worker.tasks call worker.tasks.check_platform_health
```

---

## 8. Zero-Downtime Updates

CRITICAL SECTION - Read completely before touching a production server.

### What data survives any update

The following are Docker volumes and bind mounts. They are never touched during updates.

| Data | Location | Safe During Update |
|---|---|---|
| All user data | postgres_data volume | Yes - always |
| Bot sessions | redis_data volume | Yes - always |
| Log files | ./logs/ folder | Yes - always |
| Media files | ./media/ folder | Yes - always |
| Database backups | ./backups/ folder | Yes - always |
| Environment config | .env file | Yes - always |
| Translations | ./translations/ folder | Yes - always |

### Update types and risk level

| Type of Change | Risk | Downtime |
|---|---|---|
| Bug fix or logic change | Low | 2 seconds |
| New feature without DB change | Low | 2 seconds |
| New DB column or table | Medium | 30 to 60 seconds |
| Removing a DB column | High | Follow careful steps below |

---

### 8.1 Standard update - no database changes

Use this for most code updates: bug fixes, UI changes, logic improvements.

```bash
cd /home/stf/socialtofeed

# Step 1: Upload new code
git pull
# OR upload new zip and extract files

# Step 2: Build new Docker image (containers keep running during build)
docker compose build

# Step 3: Restart services one at a time in this exact order
docker compose up -d --no-deps worker
sleep 10

docker compose up -d --no-deps beat
sleep 5

docker compose up -d --no-deps admin
sleep 5

# Last step: restart the bot (causes about 2 second disconnect for users)
docker compose up -d --no-deps bot

# Step 4: Verify everything is running
docker compose ps
docker compose logs bot --tail=30
```

NOTE: Why this order? Worker and beat are not user-facing. Restarting them first lets you test new code on background tasks before touching the bot that users interact with.

---

### 8.2 Update with database migration

Use this when you added new columns, tables, or changed the schema.

```bash
cd /home/stf/socialtofeed

# Step 1: Upload new code
git pull

# Step 2: Build new Docker image
docker compose build

# Step 3: Stop user-facing services
# DB and Redis keep running - data is completely safe
docker compose stop bot
docker compose stop worker
docker compose stop beat

# Step 4: Run database migration
docker compose run --rm bot python -m alembic upgrade head
# Expected: Running upgrade xxx -> yyy, OK

# If Django admin models also changed:
docker compose run --rm admin python manage.py migrate --noinput

# Step 5: Start everything back up
docker compose up -d

# Step 6: Verify
docker compose ps
docker compose logs bot --tail=50
docker compose logs worker --tail=20
```

Total downtime: 30 to 60 seconds only.

---

### 8.3 Emergency rollback

Use this if the new version has a critical bug and you need to go back immediately.

```bash
# Step 1: Stop everything
docker compose down

# Step 2: Restore old code
git checkout v3.1
# OR restore previous zip

# Step 3: If you ran a migration, roll it back
docker compose run --rm bot python -m alembic downgrade -1
# This undoes the last migration only

# Step 4: Rebuild and restart old version
docker compose build
docker compose up -d

# Step 5: Verify everything is back to normal
docker compose logs -f bot --tail=30
```

---

## 9. Database Migrations

### Check current migration state

```bash
docker compose run --rm bot python -m alembic current
# Shows which revision is currently applied to the database
```

### View full migration history

```bash
docker compose run --rm bot python -m alembic history --verbose
```

### Apply latest migration

```bash
docker compose run --rm bot python -m alembic upgrade head
```

### Roll back one step

```bash
docker compose run --rm bot python -m alembic downgrade -1
```

### Create a new migration after editing bot/models.py

```bash
# Auto-generate based on model changes
docker compose run --rm bot python -m alembic revision --autogenerate -m "describe_your_change"

# Review the generated file in alembic/versions/
# Then apply it
docker compose run --rm bot python -m alembic upgrade head
```

### Fix a failed migration

```bash
# Check current state
docker compose run --rm bot python -m alembic current

# Connect to database and fix manually if needed
docker compose exec db psql -U stfuser socialtofeed

# Mark migration as applied without running it
docker compose run --rm bot python -m alembic stamp head

# Or completely reset and re-apply all migrations
# WARNING: Only use this on a fresh database - destroys existing data
docker compose run --rm bot python -m alembic downgrade base
docker compose run --rm bot python -m alembic upgrade head
```

---

## 10. RSSHub Cookie Refresh

IMPORTANT: Do this every 2 to 4 weeks. Expired cookies mean Twitter, Instagram, and TikTok posts stop arriving.

### Signs that cookies need refreshing

- Posts from Twitter, Instagram, or TikTok stopped arriving
- System logs show: 403 Forbidden from RSSHub
- Admin receives a Telegram alert about RSSHub returning 403
- check_platform_health task reports a platform is down

### How to get fresh cookies

Open Chrome or Firefox in Incognito mode. Log in to the platform using a spare account.

**For Twitter / X:**
- Go to: https://twitter.com
- Open DevTools (F12) then Application then Cookies then twitter.com
- Copy the auth_token value and ct0 value
- Format for .env:
```
RSSHUB_COOKIE_TWITTER=auth_token=PASTE_HERE; ct0=PASTE_HERE
```

**For Instagram:**
- Go to: https://www.instagram.com
- Open DevTools (F12) then Application then Cookies then instagram.com
- Copy the sessionid value and csrftoken value
- Format for .env:
```
RSSHUB_COOKIE_INSTAGRAM=sessionid=PASTE_HERE; csrftoken=PASTE_HERE
```

**For TikTok:**
- Go to: https://www.tiktok.com
- Open DevTools (F12) then Application then Cookies then tiktok.com
- Copy the sessionid value and ttwid value
- Format for .env:
```
RSSHUB_COOKIE_TIKTOK=sessionid=PASTE_HERE; ttwid=PASTE_HERE
```

### Update cookies without any downtime

```bash
cd /home/stf/socialtofeed

# Edit .env with new cookie values
nano .env

# Restart ONLY rsshub - bot stays fully up with zero interruption
docker compose up -d --no-deps rsshub

# Verify it works
docker compose logs rsshub --tail=10

# Test a feed directly
curl "http://localhost:1200/twitter/user/elonmusk" | head -5
# Should return XML feed - if 403, the cookie format is wrong
```

### Set a monthly reminder

```bash
crontab -e

# Add this line to remind you on the 1st of every month at 9AM
0 9 1 * * echo "REMINDER: Refresh RSSHub cookies for Twitter/Instagram/TikTok"
```

---

## 11. Backup and Recovery

### Automatic backups

The stf_backup container runs pg_dump every day at 3:00 AM UTC and saves to ./backups/. It keeps the last 7 days only.

```bash
# View existing backups
ls -lh /home/stf/socialtofeed/backups/

# Create a manual backup right now
docker compose exec backup sh -c \
  "pg_dump -h db -U stfuser socialtofeed | gzip > /backups/manual_$(date +%Y%m%d_%H%M%S).sql.gz"
```

### Copy backups offsite

WARNING: Backups stored on the same VPS are not real backups. If the server is destroyed, you lose everything. Always copy them somewhere else.

```bash
# From your local machine - copy all backups
scp stf@VPS_IP:/home/stf/socialtofeed/backups/*.sql.gz ./local_backups/

# Automate with rsync - add to crontab on your local machine
0 4 * * * rsync -avz stf@VPS_IP:/home/stf/socialtofeed/backups/ ~/backups/socialtofeed/
```

### Restore from a backup

```bash
cd /home/stf/socialtofeed

# Stop services that write to DB - keep DB running
docker compose stop bot worker beat admin

# Drop and recreate the database
docker compose exec db psql -U stfuser postgres -c "DROP DATABASE socialtofeed;"
docker compose exec db psql -U stfuser postgres -c "CREATE DATABASE socialtofeed;"

# Restore from the backup file
gunzip -c backups/stf_backup_20250530_030001.sql.gz | \
  docker compose exec -T db psql -U stfuser socialtofeed

# Re-apply migrations to ensure schema is current
docker compose run --rm bot python -m alembic upgrade head

# Start everything
docker compose up -d

# Verify data is intact
docker compose exec db psql -U stfuser socialtofeed -c "SELECT COUNT(*) FROM users;"
```

### Full recovery on a new VPS

```bash
# 1. Complete sections 3.1 to 3.3 on the new VPS (install Docker, create user, upload files)
# 2. Copy your .env file to the new server (keep this file backed up separately)
# 3. Start DB and Redis only
docker compose up -d db redis

# 4. Restore from backup file (follow restore steps above)

# 5. Deploy everything
docker compose up -d

# Total recovery time: 15 to 20 minutes
```

---

## 12. Monitoring and Logs

### View live logs

```bash
# All services together
docker compose logs -f

# Single service
docker compose logs -f bot
docker compose logs -f worker
docker compose logs -f rsshub

# Last 100 lines only
docker compose logs --tail=100 bot

# Since a specific time
docker compose logs --since="2025-05-30T10:00:00" bot
```

### Check container health

```bash
# Quick status of all containers
docker compose ps

# Resource usage: CPU, RAM, network
docker stats --no-stream
```

### Useful database queries

```bash
# Connect to PostgreSQL
docker compose exec db psql -U stfuser socialtofeed

# Count all users
SELECT COUNT(*) FROM users;

# Users by plan
SELECT plan, COUNT(*) FROM users GROUP BY plan;

# Active accounts
SELECT COUNT(*) FROM accounts WHERE is_active = true;

# Pending payments
SELECT COUNT(*) FROM transactions WHERE status = 'pending';

# Check for stuck payments (pending for more than 7 days)
SELECT id, user_id, amount_usdt, network, created_at
FROM transactions
WHERE status = 'pending'
  AND created_at < NOW() - INTERVAL '7 days';

# Exit psql
\q
```

### Check Redis

```bash
docker compose exec redis redis-cli -a $REDIS_PASSWORD

INFO memory
DBSIZE
GET rsshub_healthy

exit
```

### Admin panel access

```
URL:   https://admin.aisocialfeed.com/admin
Login: the superuser you created in step 5.3
```

### Telegram admin alerts

The bot automatically sends alerts to your ADMIN_TELEGRAM_ID for these events:
- RSSHub going down
- Subscription expiry warnings
- Daily growth report
- All ERROR and CRITICAL level log events

To test alerts manually:
```bash
docker compose stop rsshub
# Wait 15 minutes
# You should receive a Telegram message
docker compose start rsshub
```

---

## 13. Troubleshooting Guide

### Problem: Bot not responding to messages

```bash
# Check container status
docker compose ps bot

# Check logs for errors
docker compose logs bot --tail=50

# Cause 1: Invalid bot token
docker compose logs bot | grep "Unauthorized"
# Fix: verify BOT_TOKEN in .env

# Cause 2: Webhook conflict
docker compose logs bot | grep "Conflict"
# Fix:
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
docker compose restart bot

# Cause 3: Database connection failed
docker compose logs bot | grep "could not connect"
# Fix:
docker compose restart db
docker compose restart bot
```

### Problem: Posts not being delivered to users

```bash
# Check if worker is running
docker compose ps worker

# Check if beat is scheduling tasks
docker compose logs beat --tail=20
# Should show: Sending due task schedule_pending_fetches

# Check if worker processes tasks
docker compose logs worker --tail=50
# Should show: Task fetch_account_task succeeded

# Manually trigger fetch
docker compose exec worker celery -A worker.tasks call \
  worker.tasks.schedule_pending_fetches

# Check for platform errors
docker compose logs worker | grep "ERROR" | tail -20
```

### Problem: Instagram or Twitter feeds stopped

```bash
# Test RSSHub directly
curl "http://localhost:1200/twitter/user/elonmusk"
# Should return an XML RSS feed

# If you see 403:
# Cookies are expired - follow section 10 to get new cookies

# Check RSSHub logs
docker compose logs rsshub --tail=30

# Restart RSSHub
docker compose restart rsshub
```

### Problem: Payments not activating

```bash
# Check pending transactions in database
docker compose exec db psql -U stfuser socialtofeed -c \
  "SELECT id, user_id, amount_usdt, network, status, created_at
   FROM transactions WHERE status='pending';"

# Check payment monitor logs
docker compose logs worker | grep "monitor_payment"

# Check CoinEx API logs
docker compose logs worker | grep "CoinEx"

# Manually run payment monitor for a specific transaction
docker compose exec worker celery -A worker.tasks call \
  worker.tasks.monitor_payment_task --args='[TRANSACTION_ID]'
```

### Problem: AI features not working

```bash
# Test DeepSeek API key
curl https://api.deepseek.com/v1/models \
  -H "Authorization: Bearer YOUR_DEEPSEEK_KEY"
# Should return a list of available models

# Check daily limit in Redis
docker compose exec redis redis-cli -a $REDIS_PASSWORD KEYS "ai:daily:*"

# Check AI logs
docker compose logs worker | grep -i "deepseek\|AI" | tail -20
```

### Problem: Container keeps restarting

```bash
# Find which container is restarting
docker compose ps

# Read its crash logs
docker compose logs CONTAINER_NAME --tail=50

# Common causes and fixes:
# Missing .env variable    -> add it to .env and restart
# Database not ready       -> wait for healthy status
# Out of memory            -> run: free -h
# Port already in use      -> run: ss -tulpn | grep 8000
```

### Problem: Disk space full

```bash
# Check overall disk usage
df -h

# Find large directories
du -sh /home/stf/socialtofeed/media/*
du -sh /home/stf/socialtofeed/logs/*
du -sh /home/stf/socialtofeed/backups/*

# Delete old logs (older than 7 days)
find /home/stf/socialtofeed/logs -name "*.log" -mtime +7 -delete

# Remove unused Docker images
docker image prune -f

# Delete old downloaded media files (older than 24 hours)
find /home/stf/socialtofeed/media/downloads -mtime +1 -delete
```

### Problem: Database running slow

```bash
# Check database size
docker compose exec db psql -U stfuser -c \
  "SELECT pg_size_pretty(pg_database_size('socialtofeed'));"

# Find the largest tables
docker compose exec db psql -U stfuser socialtofeed -c "
SELECT relname AS table_name,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;"

# Run cleanup task manually
docker compose exec worker celery -A worker.tasks call \
  worker.tasks.cleanup_old_posts

# Run PostgreSQL maintenance
docker compose exec db psql -U stfuser socialtofeed -c "VACUUM ANALYZE;"
```

---

## 14. Security Hardening

### Step 14.1 - Set up firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
# Do NOT open port 8000 - use Nginx reverse proxy instead
ufw enable
ufw status verbose
```

### Step 14.2 - Restrict admin panel to your IP

Add to the Nginx config for admin.aisocialfeed.com:

```nginx
allow YOUR_HOME_IP;
allow YOUR_OFFICE_IP;
deny all;
```

### Step 14.3 - Enable Fail2Ban protection

```bash
cat > /etc/fail2ban/jail.local << EOF
[sshd]
enabled = true
port = ssh
maxretry = 5
bantime = 3600
findtime = 600
EOF

systemctl restart fail2ban
fail2ban-client status sshd
```

### Step 14.4 - Disable root SSH login

```bash
nano /etc/ssh/sshd_config

# Change these two lines:
PermitRootLogin no
PasswordAuthentication no

systemctl restart sshd
```

### Step 14.5 - Protect your secrets

```bash
# Never commit .env to any Git repository
echo ".env" >> .gitignore
echo "backups/" >> .gitignore

# Keep a secure offline backup of:
# - .env file (all API keys and passwords)
# - Admin superuser password
# - CoinEx API keys
# - Telegram bot token
```

### Step 14.6 - How to rotate secrets if compromised

```bash
# Rotate Telegram bot token:
# Message @BotFather -> /mybots -> choose bot -> API Token -> Revoke

# Rotate CoinEx keys:
# Go to coinex.com/account/api -> Delete old key -> Create new key

# Rotate ENCRYPTION_KEY:
# Generate a new key (see section 3.4)
# Update .env
# Re-encrypt any encrypted database values via admin panel
```

---

## 15. Scaling Guide

### Increase Celery worker concurrency

Edit docker-compose.yml:

```yaml
worker:
  command: celery -A worker.celery_app worker --loglevel=info --concurrency=8 -Q default,platforms,ai,downloads
```

```bash
docker compose up -d --no-deps worker
```

### Add a second worker container

Add this to docker-compose.yml under services:

```yaml
worker2:
  build:
    context: .
    dockerfile: docker/Dockerfile
  command: celery -A worker.celery_app worker --loglevel=info --concurrency=4 -Q platforms
  env_file: .env
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_healthy
  volumes:
    - ./logs:/app/logs
    - ./media:/app/media
  networks:
    - stf_net
```

### Increase database connection pool

Edit config/settings.py:

```python
class DatabaseConfig:
    pool_size: int = 20       # was 10
    max_overflow: int = 40    # was 20
```

### Increase Redis memory limit

Edit docker-compose.yml redis section:

```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 1gb --maxmemory-policy allkeys-lru
```

### When to upgrade your VPS

| Warning Sign | Recommended Action |
|---|---|
| CPU consistently over 70% | Upgrade to next server tier |
| RAM consistently over 80% | Upgrade to next server tier |
| DB queries taking over 500ms | Add indexes or upgrade server |
| Redis memory over 80% | Increase memory limit |
| Celery task queue over 500 tasks | Add more worker concurrency |

```bash
# Check current resource usage
docker stats --no-stream
```

---

## 16. Quick Reference Card

### Most used commands

```bash
# Start everything
docker compose up -d

# Stop everything - data is always safe
docker compose down

# Restart one service
docker compose restart bot

# View live logs
docker compose logs -f bot

# Rebuild after code change
docker compose build

# Standard update - no DB changes
docker compose build
docker compose up -d --no-deps worker
docker compose up -d --no-deps beat
docker compose up -d --no-deps admin
docker compose up -d --no-deps bot

# Update with migration
docker compose build
docker compose stop bot worker beat
docker compose run --rm bot python -m alembic upgrade head
docker compose up -d

# Manual database backup
docker compose exec backup sh -c \
  "pg_dump -h db -U stfuser socialtofeed | gzip > /backups/manual_$(date +%Y%m%d).sql.gz"

# Connect to PostgreSQL
docker compose exec db psql -U stfuser socialtofeed

# Connect to Redis
docker compose exec redis redis-cli -a $REDIS_PASSWORD

# Check container health
docker compose ps

# Check CPU and memory usage
docker stats --no-stream

# Check disk space
df -h

# Trigger a task manually
docker compose exec worker celery -A worker.tasks call \
  worker.tasks.check_platform_health

# Test RSSHub is working
curl http://localhost:1200/twitter/user/elonmusk | head -5

# Refresh cookies without downtime
nano .env
docker compose up -d --no-deps rsshub

# Roll back last database migration
docker compose run --rm bot python -m alembic downgrade -1
```

---

SocialtoFeed v3.2 - Developer Guide - May 2026
All commands are tested against the actual docker-compose.yml and project code.
