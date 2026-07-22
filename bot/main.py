"""
SocialtoFeed — Bot Entry Point
Initializes database, loads translations, starts bot (webhook or polling).
"""

import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from config import config
from bot.database import init_db, close_db
from bot.utils.logger import setup_logging, STFLogger
from bot.utils.telegram_utils import set_bot
from bot.utils.translator import load_translations
from bot.models import LogModule

log = STFLogger(LogModule.BOT)
logger = logging.getLogger(__name__)


def _register_handlers(app: Application) -> None:
    """Register all handlers — imported here to avoid circular imports.

    Order matters:
    1. admin_tg first — its ConversationHandlers (search, broadcast) must take
       priority over the generic TEXT MessageHandler in start.py (text_router).
    2. start last among core handlers — text_router is a catch-all.
    """
    from bot.handlers.admin_tg import register as reg_admin_tg
    from bot.handlers.start import register as reg_start
    from bot.handlers.accounts import register as reg_accounts
    from bot.handlers.payment import register as reg_payment
    from bot.handlers.profile import register as reg_profile
    from bot.handlers.support import register as reg_support
    from bot.handlers.categories import register as reg_categories
    from bot.handlers.video import register as reg_video
    from bot.handlers.bookmarks import register as reg_bookmarks
    from bot.handlers.status import register as reg_status
    from bot.handlers.share_bot import register as reg_share
    from bot.handlers.crypto_payment import register as reg_crypto

    reg_admin_tg(app)
    reg_accounts(app)
    reg_payment(app)
    reg_profile(app)
    reg_support(app)
    reg_categories(app)
    reg_video(app)
    reg_bookmarks(app)
    reg_status(app)
    reg_share(app)
    reg_crypto(app)
    reg_start(app)

    logger.info("All handlers registered.")


async def _post_init(app: Application) -> None:
    """Called after bot is initialized — before start."""
    set_bot(app.bot)
    load_translations()
    await init_db()

    # Log startup warnings
    warnings = config.validate()
    for w in warnings:
        logger.warning(f"Config warning: {w}")

    await log.info("SocialtoFeed bot starting up.", extra={"warnings": warnings})
    logger.info("Bot initialized successfully.")


async def _post_shutdown(app: Application) -> None:
    """Called on shutdown."""
    await close_db()
    from bot.cache import close_redis
    await close_redis()
    await log.info("SocialtoFeed bot shut down.")


def build_app() -> Application:
    """Build and configure the Application with RedisPersistence (state survives restarts)."""
    from bot.utils.redis_persistence import RedisPersistenceBackend
    persistence = RedisPersistenceBackend(redis_url=config.redis.url)
    logger.info("Using RedisPersistence — state survives restarts.")

    builder = (
        ApplicationBuilder()
        .token(config.telegram.token)
        .persistence(persistence)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .concurrent_updates(True)
    )

    # Fix 5: Proxy support for restricted networks (Iran, China, etc.)
    # Set HTTPS_PROXY=socks5://user:pass@host:port  OR  http://host:port in .env
    import os
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("HTTP_PROXY")
    if proxy_url:
        from telegram.request import HTTPXRequest
        builder = builder.request(HTTPXRequest(proxy=proxy_url))
        logger.info(f"Using proxy for Telegram API: {proxy_url.split('@')[-1]}")  # hide credentials in log

    app = builder.build()
    return app


def main() -> None:
    setup_logging()
    logger.info("=" * 50)
    logger.info("  SocialtoFeed Bot Starting")
    logger.info("=" * 50)

    app = build_app()

    # Register handlers synchronously — no asyncio.run() needed since
    # app.add_handler() is sync. asyncio.run() was destroying the event loop
    # before run_polling() could use it (RuntimeError: no current event loop).
    _register_handlers(app)

    if config.telegram.webhook_url:
        # Webhook mode (production)
        # DEAD-4 fix: strip any trailing /webhook from env var before appending
        # so WEBHOOK_URL=https://example.com/webhook doesn't become .../webhook/webhook
        base_url = config.telegram.webhook_url.rstrip("/").removesuffix("/webhook")
        webhook_url = f"{base_url}/webhook"
        logger.info(f"Starting in WEBHOOK mode: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=8443,
            webhook_url=webhook_url,
            url_path="/webhook",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Polling mode (development / fallback)
        logger.info("Starting in POLLING mode.")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)