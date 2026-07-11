from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from cairn.api.errors import register_error_handlers
from cairn.api.middleware.request_logging import request_logging_middleware
from cairn.api.v1.middleware import require_active_campaign
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
from cairn.application.turns.epilogue import post_turn_epilogue
from cairn.config import get_settings
from cairn.observability.logging import configure_logging
from cairn.pipelines.checkpointer import lifespan_checkpointer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with lifespan_checkpointer(settings.database_url):
        try:
            yield
        finally:
            await post_turn_epilogue.shutdown()


def create_app() -> FastAPI:
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.middleware("http")(request_logging_middleware)

    register_error_handlers(app)
    # Mutating routes on a dead (hardcore) campaign are frozen; reads stay open. SRD is global.
    frozen_guard = [Depends(require_active_campaign)]
    app.include_router(campaigns.router, dependencies=frozen_guard)
    app.include_router(characters.router, dependencies=frozen_guard)
    app.include_router(combat.router, dependencies=frozen_guard)
    app.include_router(loot.router, dependencies=frozen_guard)
    app.include_router(npcs.router, dependencies=frozen_guard)
    app.include_router(sessions.router, dependencies=frozen_guard)
    app.include_router(srd.router)
    app.include_router(turns.router, dependencies=frozen_guard)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
