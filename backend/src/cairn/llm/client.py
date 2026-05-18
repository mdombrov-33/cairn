import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import litellm
import structlog
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from litellm import CustomStreamWrapper
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from cairn.domain.exceptions import AgentError, LLMError, ToolError

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


async def _invoke_tool(t: BaseTool, args: dict) -> Any:
    return await t.ainvoke(args)


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


async def complete_to_model[T: BaseModel](
    *,
    model: str,
    messages: list[dict[str, str]],
    model_cls: type[T],
    agent: str = "unknown",
    fallbacks: list[str] | None = None,
    **kwargs: Any,
) -> T:
    raw = await complete(model=model, messages=messages, agent=agent, fallbacks=fallbacks, **kwargs)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return model_cls.model_validate_json(cleaned)
    except ValidationError as exc:
        log.error(f"{agent}_bad_output", raw=raw, error=str(exc))
        raise AgentError(f"{agent} returned invalid output: {raw!r}") from exc


async def complete_with_tools(
    model: str,
    messages: list[dict],
    tools: list[BaseTool],
    agent: str = "unknown",
    fallbacks: list[str] | None = None,
    max_iterations: int = 15,
    **kwargs: Any,
) -> tuple[str, list[dict]]:
    """Run a tool-calling loop until the model stops requesting tool calls.

    Returns (final_text_response, full_message_history).
    Raises LLMError on LLM failure or ToolError on tool failure.
    """
    oai_tools = [convert_to_openai_tool(t) for t in tools]
    tool_map = {t.name: t for t in tools}
    msgs: list[dict] = list(messages)

    for iteration in range(max_iterations):
        t0 = time.perf_counter()
        try:
            response = await _call(model, msgs, fallbacks or [], tools=oai_tools, **kwargs)
        except Exception as exc:
            log.error("llm_error", model=model, agent=agent, error=str(exc))
            raise LLMError(str(exc)) from exc

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        log.info(
            "llm_tool_loop",
            model=model,
            agent=agent,
            iteration=iteration,
            has_tool_calls=bool(tool_calls),
            duration_ms=duration_ms,
        )

        if not tool_calls:
            content = msg.content or ""
            return content, msgs

        msgs.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            if name not in tool_map:
                log.warning("tool_call_unknown", tool=name, agent=agent)
                result: Any = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = await _invoke_tool(tool_map[name], args)
                except Exception as exc:
                    log.error(
                        "tool_call_failed", tool=name, agent=agent, error=str(exc), exc_info=True
                    )
                    raise ToolError(f"Tool '{name}' failed: {exc}") from exc

            log.info("tool_call", tool=name, agent=agent)
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )

    raise LLMError(f"Tool loop exceeded {max_iterations} iterations without finishing.")


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
