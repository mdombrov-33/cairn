from fastapi import FastAPI

from cairn.api.errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="Cairn")

    register_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
