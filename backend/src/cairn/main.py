from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI
from mcp.server.fastmcp import FastMCP

from cairn.api.errors import register_error_handlers
from cairn.api.mcp import build_mcp_server
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
from cairn.config import Settings, get_settings
from cairn.observability.logging import configure_logging
from cairn.pipelines.checkpointer import lifespan_checkpointer


def _lifespan(settings: Settings, mcp_server: FastMCP | None):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan_checkpointer(settings.database_url))
            if mcp_server is not None:
                await stack.enter_async_context(mcp_server.session_manager.run())
            try:
                yield
            finally:
                await post_turn_epilogue.shutdown()

    return lifespan


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    configure_logging(settings)

    mcp_server = build_mcp_server() if settings.is_mcp_enabled() else None
    app = FastAPI(title=settings.app_name, lifespan=_lifespan(settings, mcp_server))
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
    if mcp_server is not None:
        app.mount("/mcp", mcp_server.streamable_http_app())

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
