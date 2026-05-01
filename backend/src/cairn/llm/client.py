import time
from collections.abc import AsyncIterator
from typing import Any, cast

import litellm
import structlog
from litellm import CustomStreamWrapper
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from cairn.domain.exceptions import LLMError

log = structlog.get_logger()

_RETRYABLE = (
    Timeout,
    RateLimitError,
    ServiceUnavailableError,
    APIConnectionError,
    InternalServerError,
)


@retry(
    retry=retry_if_exception_type(_RETRYABLE),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _call(
    model: str,
    messages: list[dict[str, str]],
    fallbacks: list[str],
    **kwargs: Any,
) -> Any:

    return await litellm.acompletion(
        model=model, messages=messages, fallbacks=fallbacks or None, **kwargs
    )


async def complete(
    model: str,
    messages: list[dict[str, str]],
    agent: str = "unknown",
    fallbacks: list[str] | None = None,
    **kwargs: Any,
) -> str:
    """Call the LLM and return the text content. Retries on transient errors."""
    t0 = time.perf_counter()
    try:
        response = await _call(model, messages, fallbacks or [], **kwargs)
    except Exception as exc:
        log.error(
            "llm_error",
            model=model,
            agent=agent,
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        raise LLMError(str(exc)) from exc

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    usage = getattr(response, "usage", None)
    log.info(
        "llm_complete",
        model=model,
        agent=agent,
        duration_ms=duration_ms,
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )

    content: str | None = response.choices[0].message.content
    if content is None:
        raise LLMError("LLM returned empty content")
    return content


async def stream(
    model: str,
    messages: list[dict[str, str]],
    agent: str = "unknown",
    fallbacks: list[str] | None = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Call the LLM with streaming and yield text chunks. No retry — caller handles partial streams."""  # noqa: E501
    t0 = time.perf_counter()
    try:
        response = cast(
            CustomStreamWrapper,
            await litellm.acompletion(
                model=model,
                messages=messages,
                stream=True,
                fallbacks=fallbacks or None,
                **kwargs,
            ),
        )
        async for chunk in response:
            text = chunk.choices[0].delta.content or ""
            if text:
                yield text
    except Exception as exc:
        log.error("llm_stream_error", model=model, agent=agent, error=str(exc))
        raise LLMError(str(exc)) from exc
    finally:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        log.info("llm_stream_complete", model=model, agent=agent, duration_ms=duration_ms)
