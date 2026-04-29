from fastapi import FastAPI

from cairn.api.errors import register_error_handlers
from cairn.api.middleware.request_logging import request_logging_middleware
from cairn.api.v1.routes import campaigns, sessions, turns
from cairn.config import get_settings
from cairn.observability.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name)
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
