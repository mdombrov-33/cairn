from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cairn.api.errors import register_error_handlers
from cairn.api.middleware.request_logging import request_logging_middleware
from cairn.api.v1.routes import campaigns, sessions, turns
from cairn.config import get_settings
from cairn.observability.logging import configure_logging
from cairn.pipelines.checkpointer import lifespan_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with lifespan_checkpointer(settings.database_url):
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.middleware("http")(request_logging_middleware)

    register_error_handlers(app)
    app.include_router(campaigns.router)
    app.include_router(sessions.router)
    app.include_router(turns.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
