from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.tools import BaseTool, StructuredTool, tool

ToolTag = Literal[
    "dice",
    "srd",
    "readonly",
    "combat",
    "resource",
    "rest",
    "state",
    "mutation",
    "narrative",
]
ToolFunction = Callable[..., Coroutine[Any, Any, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    tool: StructuredTool
    tags: frozenset[ToolTag]
    mcp: bool


_REGISTRY: dict[str, RegisteredTool] = {}


def register(*, tags: set[ToolTag], mcp: bool = True) -> Callable[[ToolFunction], StructuredTool]:
    """Create one LangChain tool and record its projections."""
    frozen_tags = frozenset(tags)
    if not frozen_tags:
        raise ValueError("registered tools require at least one tag")

    def decorator(function: ToolFunction) -> StructuredTool:
        registered_tool = cast(StructuredTool, tool(function))
        if registered_tool.name in _REGISTRY:
            raise ValueError(f"duplicate tool name: {registered_tool.name}")
        _REGISTRY[registered_tool.name] = RegisteredTool(
            tool=registered_tool,
            tags=frozen_tags,
            mcp=mcp,
        )
        return registered_tool

    return decorator


def all() -> list[BaseTool]:
    return [registered.tool for registered in _REGISTRY.values()]


def select(*, include: set[ToolTag], exclude: set[ToolTag] | None = None) -> list[BaseTool]:
    excluded = exclude or set()
    return [
        registered.tool
        for registered in _REGISTRY.values()
        if registered.tags.issuperset(include) and registered.tags.isdisjoint(excluded)
    ]


def mcp_tools() -> list[RegisteredTool]:
    return [registered for registered in _REGISTRY.values() if registered.mcp]
