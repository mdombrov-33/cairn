import os
from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch

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

_FAKE_STREAM_TOKENS = ["The tavern ", "is quiet ", "tonight."]
_FAKE_CHECK_JSON = '{"skill": "persuasion", "dc": 14, "modifier": 4, "roll_type": "d20"}'
_FAKE_NPC_JSON = '{"dialogue": "Aye, what\'ll it be?", "disposition_change": null}'
_FAKE_LORE_JSON = '[{"type": "NPC", "key": "old_grim_bartender", "content": "Old Grim is the gruff bartender of the Grimwood Tavern, a retired soldier."}]'  # noqa: E501


async def _fake_acompletion(model: str, messages: list, stream: bool = False, **kwargs):  # type: ignore[return]
    if stream:

        async def _gen():
            for text in _FAKE_STREAM_TOKENS:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = text
                yield chunk

        return _gen()
    else:
        content = messages[-1].get("content", "") if messages else ""
        if "NPC:" in content and "disposition" in content:
            reply = _FAKE_NPC_JSON
        elif "skill" in content and "dc" in content.lower() and "modifier" in content:
            reply = _FAKE_CHECK_JSON
        elif "QUEST" in content and "world bible" in content.lower():
            reply = _FAKE_LORE_JSON
        else:
            reply = "narrative_action"
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = reply
        response.usage = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5
        return response


@pytest.fixture(autouse=True)
def fake_llm():
    with (
        patch("litellm.acompletion", side_effect=_fake_acompletion),
        patch("cairn.pipelines.turn_graph.run", return_value=("narrative_action", None)),
    ):
        yield


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
