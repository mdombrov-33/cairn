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


async def _fake_turn_graph_run(player_input, session_id, campaign_id):
    # Mirror the real graph's combat short-circuit: an active combat resolves as a
    # combat_action. Everything else falls through to narrative_action (the Scene Director
    # and intent router are exercised in unit tests, not through this integration fake).
    import uuid

    from cairn.db.queries import sessions as session_queries

    async with db_client.get_session() as db:
        db_session = await session_queries.get_session(db, uuid.UUID(str(session_id)))
        intent = "combat_action" if db_session.combat_active else "narrative_action"

    return {
        "session_id": str(session_id),
        "campaign_id": str(campaign_id),
        "player_input": player_input,
        "intent": intent,
        "npc_name": None,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": None,
        "is_scene_entry": False,
        "combat_just_started": False,
    }


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
        patch("cairn.pipelines.turn_graph.run", side_effect=_fake_turn_graph_run),
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

    # Drain fire-and-forget background tasks (lore_keeper, scene_director_post) before
    # truncating — their in-flight queries otherwise deadlock against the TRUNCATE's
    # exclusive lock. They're tagged "cairn-bg" so we wait only on ours, with a safety timeout.
    import asyncio

    bg = [t for t in asyncio.all_tasks() if t.get_name() == "cairn-bg"]
    if bg:
        await asyncio.wait(bg, timeout=5)

    engine = db_client.get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename != 'alembic_version'")
        )
        tables = [row[0] for row in result]
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _seed_template() -> None:
    """Seed the tavern_v1 world + template before each test.

    Campaign creation resolves template_id against a seeded CampaignTemplate row, and
    the truncate fixture wipes seed tables between tests, so re-seed each time.
    """
    from cairn.cli.seed import run as seed_run

    await seed_run("tavern_v1")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # Inline: cairn.main runs `app = create_app()` at module load, which reads
    # DATABASE_URL via get_settings(). Must import after _postgres_and_migrate sets it.
    from cairn.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
