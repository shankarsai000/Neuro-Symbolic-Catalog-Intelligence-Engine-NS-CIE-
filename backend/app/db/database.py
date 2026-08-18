from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

# Database URL configuration with SQLite async fallback for tests/local
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./nscie.db",
)

# Convert standard postgres:// or postgresql:// to postgresql+asyncpg:// if needed
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Build engine configuration based on dialect
engine_kwargs: dict[str, Any] = {
    "echo": False,
    "future": True,
}

if "sqlite" in DATABASE_URL:
    engine_kwargs["connect_args"] = {"timeout": 60.0}
else:
    # Production PostgreSQL connection pool settings
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    })

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    **engine_kwargs,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def check_db_connectivity(max_retries: int = 5, retry_delay: float = 2.0) -> bool:
    """Verify database connectivity with exponential backoff on startup."""
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connectivity check succeeded.")
            return True
        except Exception as e:
            logger.warning(
                f"Database connectivity check attempt {attempt}/{max_retries} failed: {e}"
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_delay * attempt)
            else:
                logger.error("Database connectivity check failed after all retry attempts.")
                raise e
    return False


async def init_db() -> None:
    """Initialize database tables and optimize SQLite WAL mode if using SQLite."""
    async with engine.begin() as conn:
        if "sqlite" in DATABASE_URL:
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA busy_timeout=60000;"))
            await conn.execute(text("PRAGMA foreign_keys=ON;"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session with automatic commit/rollback."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def transactional_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone transactional unit-of-work."""
    async with async_session() as session:
        try:
            async with session.begin():
                yield session
        except Exception:
            await session.rollback()
            raise
