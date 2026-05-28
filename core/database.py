from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from models.base import Base  # noqa: F401 — re-exported so Alembic & tests can import from here

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Sync session — used by intelligence modules (BPI, momentum, etc.) ───────
# The intelligence layer mirrors the worker pattern (sync SQLAlchemy) because
# the analytics queries are CPU-bound rollups that don't benefit from async.
sync_engine = create_engine(
    settings.DATABASE_SYNC_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)


def get_sync_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a sync Session for intelligence endpoints."""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
