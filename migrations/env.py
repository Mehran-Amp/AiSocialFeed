"""
SocialtoFeed — Alembic Migration Environment

Reads DATABASE_URL from environment variables directly so it works
inside Docker without configparser interpolation issues.

Usage: alembic upgrade head
"""
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

from bot.models import Base
target_metadata = Base.metadata


def get_url() -> str:
    """
    Read DATABASE_URL from environment. Convert asyncpg dialect to
    synchronous psycopg2 for Alembic (Alembic requires sync engine).

    asyncpg (async):  postgresql+asyncpg://user:pass@host:5432/db
    psycopg2 (sync):  postgresql+psycopg2://user:pass@host:5432/db
                  or  postgresql://user:pass@host:5432/db
    """
    url = (
        os.environ.get("DATABASE_URL")
        or alembic_config.get_main_option("sqlalchemy.url", "")
    )
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it in your .env file before running migrations."
        )
    # Alembic needs a synchronous engine — strip the asyncpg driver
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
