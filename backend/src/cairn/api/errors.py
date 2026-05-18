import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn.domain.exceptions import CairnError

log = structlog.get_logger("error")


async def cairn_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CairnError)
    if exc.http_status >= 500:
        log.error("cairn_error", code=exc.code, message=exc.message, status=exc.http_status, exc_info=True)
    else:
        log.info("cairn_error", code=exc.code, message=exc.message, status=exc.http_status)
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CairnError, cairn_error_handler)
