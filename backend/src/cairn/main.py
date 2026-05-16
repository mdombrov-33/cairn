from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cairn.api.errors import register_error_handlers
from cairn.api.middleware.request_logging import request_logging_middleware
from cairn.api.v1.routes import (
    campaigns,
    characters,
    combat,
    loot,
    npcs,
    sessions,
    srd,
    turns,
)
from cairn.config import get_settings
from cairn.observability.logging import configure_logging
from cairn.pipelines.checkpointer import lifespan_checkpointer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with lifespan_checkpointer(settings.database_url):
        yield


def create_app() -> FastAPI:
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.middleware("http")(request_logging_middleware)

    register_error_handlers(app)
    app.include_router(campaigns.router)
    app.include_router(characters.router)
    app.include_router(combat.router)
    app.include_router(loot.router)
    app.include_router(npcs.router)
    app.include_router(sessions.router)
    app.include_router(srd.router)
    app.include_router(turns.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
