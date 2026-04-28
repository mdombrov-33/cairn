import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn.domain.exceptions import (
    AgentError,
    CairnError,
    LLMError,
    NotFoundError,
    QueueError,
    RAGError,
)

_STATUS_BY_EXC: dict[type[CairnError], int] = {
    NotFoundError: 404,
    AgentError: 502,
    RAGError: 502,
    LLMError: 502,
    QueueError: 503,
}


async def cairn_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CairnError)
    status = _STATUS_BY_EXC.get(type(exc), 500)
    log = structlog.get_logger("error")
    if status >= 500:
        log.error(
            "cairn_error",
            code=exc.code,
            message=exc.message,
            status=status,
            exc_info=True,
        )
    else:
        log.info(
            "cairn_error",
            code=exc.code,
            message=exc.message,
            status=status,
        )
    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CairnError, cairn_error_handler)
