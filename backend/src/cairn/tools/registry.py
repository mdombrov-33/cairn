from collections.abc import Callable, Coroutine
from typing import Any, cast

from langchain_core.tools import StructuredTool, tool

ToolFunction = Callable[..., Coroutine[Any, Any, Any]]

_REGISTRY: dict[str, StructuredTool] = {}


def register(function: ToolFunction) -> StructuredTool:
    """Create one LangChain tool and register it for MCP projection."""
    registered_tool = cast(StructuredTool, tool(function))
    if registered_tool.name in _REGISTRY:
        raise ValueError(f"duplicate tool name: {registered_tool.name}")
    _REGISTRY[registered_tool.name] = registered_tool
    return registered_tool


def all() -> list[StructuredTool]:
    return list(_REGISTRY.values())
