"""
SocialtoFeed — Database Engine & Session Management
Async SQLAlchemy with connection pooling.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from config import config
from bot.models import Base

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Engine
# ─────────────────────────────────────────────

# Convert standard postgres:// URL to async postgresql+asyncpg://
_db_url = config.db.url.replace(
    "postgresql://", "postgresql+asyncpg://"
).replace(
    "postgres://", "postgresql+asyncpg://"
)

engine = create_async_engine(
    _db_url,
    pool_size=config.db.pool_size,
    max_overflow=config.db.max_overflow,
    pool_timeout=config.db.pool_timeout,
    pool_recycle=config.db.pool_recycle,
    pool_pre_ping=True,   # test connection before using from pool
    echo=False,           # set True only for SQL debugging
)

# ─────────────────────────────────────────────
#  Session Factory
# ─────────────────────────────────────────────

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # objects stay usable after commit
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Usage:
        async with get_session() as session:
            user = await session.get(User, user_id)
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─────────────────────────────────────────────
#  Initialization
# ─────────────────────────────────────────────

async def init_db() -> None:
    """
    Initialise the DB engine and ensure all tables exist.

    Strategy (v3.9):
    1. Verify DB connection with SELECT 1
    2. Run create_all(checkfirst=True) — creates any missing tables without
       touching tables that already exist. Safe to run alongside Alembic.
       This is a safety net for Docker environments where Alembic may fail
       silently due to configuration issues.

    Note: Alembic remains the authoritative schema manager for migrations.
    create_all handles the initial table creation when Alembic hasn't run.
    """
    # Step 1: verify connection
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection verified.")

    # Step 2: create missing tables (checkfirst=True = safe, never drops or alters)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, checkfirst=True
        ))
    logger.info("Database tables ready (create_all checkfirst=True).")


async def close_db() -> None:
    """Dispose engine connections gracefully on shutdown."""
    await engine.dispose()
    logger.info("Database connections closed.")


async def check_db_connection() -> bool:
    """Health check — returns True if DB is reachable."""
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
