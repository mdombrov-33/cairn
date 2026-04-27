from fastapi import FastAPI

from cairn.api.errors import register_error_handlers
from cairn.api.v1.routes import campaigns
from cairn.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    register_error_handlers(app)
    app.include_router(campaigns.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
