"""Async PostgreSQL engine and session factory."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def normalize_async_database_url(database_url: str) -> str:
    """Return a PostgreSQL URL using the asyncpg driver."""

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgres://")
    raise ValueError("DOTAMIND_DATABASE_URL must be a PostgreSQL URL")


@dataclass(frozen=True)
class DatabaseResources:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database_resources(database_url: str) -> DatabaseResources:
    engine = create_async_engine(
        normalize_async_database_url(database_url),
        pool_pre_ping=True,
    )
    return DatabaseResources(
        engine=engine,
        session_factory=async_sessionmaker(
            engine,
            expire_on_commit=False,
            autoflush=False,
        ),
    )


async def ping_database(engine: AsyncEngine) -> None:
    """Fail startup explicitly when PostgreSQL is unavailable."""

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database(resources: DatabaseResources) -> None:
    await resources.engine.dispose()
