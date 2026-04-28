import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-Id"


async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    log = structlog.get_logger("request")
    log.info(
        "served",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
