import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from cairn.config import get_settings
from cairn.db import client as db_client


@pytest.fixture(scope="session", autouse=True)
def _postgres_and_migrate() -> Iterator[None]:
    with PostgresContainer("postgres:18", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        get_settings.cache_clear()
        test_engine = create_async_engine(url, poolclass=NullPool)
        db_client.get_engine = lambda: test_engine  # type: ignore[assignment]
        db_client.get_sessionmaker.cache_clear()

        command.upgrade(Config("alembic.ini"), "head")
        yield


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables() -> AsyncIterator[None]:
    yield

    engine = db_client.get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
            )
        )
        tables = [row[0] for row in result]
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # Inline: cairn.main runs `app = create_app()` at module load, which reads
    # DATABASE_URL via get_settings(). Must import after _postgres_and_migrate sets it.
    from cairn.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
