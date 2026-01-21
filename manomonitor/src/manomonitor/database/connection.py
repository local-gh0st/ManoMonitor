"""Database connection and session management."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from manomonitor.config import settings
from manomonitor.database.models import Base

logger = logging.getLogger(__name__)

# Get resolved database URL (handles relative paths for SQLite)
_database_url = settings.get_database_url()

# Create async engine
engine = create_async_engine(
    _database_url,
    echo=settings.debug,
    # SQLite-specific settings for better concurrency
    connect_args={"check_same_thread": False} if "sqlite" in _database_url else {},
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _run_migrations(conn) -> None:
    """Run simple schema migrations for SQLite."""
    # Get existing columns in assets table
    result = await conn.execute(text("PRAGMA table_info(assets)"))
    existing_columns = {row[1] for row in result.fetchall()}

    # Define migrations: (column_name, SQL to add it)
    migrations = [
        ("vendor", "ALTER TABLE assets ADD COLUMN vendor VARCHAR(200)"),
        ("device_type", "ALTER TABLE assets ADD COLUMN device_type VARCHAR(50)"),
        ("last_latitude", "ALTER TABLE assets ADD COLUMN last_latitude FLOAT"),
        ("last_longitude", "ALTER TABLE assets ADD COLUMN last_longitude FLOAT"),
        ("position_accuracy", "ALTER TABLE assets ADD COLUMN position_accuracy FLOAT"),
        ("position_updated_at", "ALTER TABLE assets ADD COLUMN position_updated_at DATETIME"),
    ]

    for column_name, sql in migrations:
        if column_name not in existing_columns:
            try:
                await conn.execute(text(sql))
                logger.info(f"Migration: Added column '{column_name}' to assets table")
            except Exception as e:
                logger.warning(f"Migration failed for column '{column_name}': {e}")


async def init_db() -> None:
    """Initialize the database, creating tables if they don't exist."""
    # Ensure data directory exists for SQLite
    db_path = settings.get_database_path()
    if db_path:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Database path: {db_path.absolute()}")

    async with engine.begin() as conn:
        # Enable WAL mode for SQLite for better concurrency
        if "sqlite" in _database_url:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB cache
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            logger.info("SQLite optimizations applied (WAL mode, etc.)")

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")

        # Run migrations for existing databases
        if "sqlite" in _database_url:
            await _run_migrations(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.

    Usage with FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Usage:
        async with get_db_context() as db:
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
    logger.info("Database connections closed")
