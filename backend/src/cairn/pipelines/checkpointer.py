from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_checkpointer: AsyncPostgresSaver | None = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("checkpointer not initialized — app lifespan not started")
    return _checkpointer


@asynccontextmanager
async def lifespan_checkpointer(database_url: str) -> AsyncIterator[None]:
    global _checkpointer
    # psycopg uses plain postgresql:// URLs, not the SQLAlchemy postgresql+asyncpg:// form
    psycopg_url = database_url.replace("+asyncpg", "")
    async with AsyncPostgresSaver.from_conn_string(psycopg_url) as checkpointer:
        await checkpointer.setup()
        _checkpointer = checkpointer
        yield
    _checkpointer = None
