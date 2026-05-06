from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Tool:
    fn: Callable[..., Awaitable[Any]]
    spec: dict

    @property
    def name(self) -> str:
        return self.spec["function"]["name"]


def prop(type_: str, description: str, **extra: Any) -> dict:
    return {"type": type_, "description": description, **extra}


def tool(
    description: str,
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Tool]:
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Tool:
        return Tool(
            fn=fn,
            spec={
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        **({"required": required} if required else {}),
                    },
                },
            },
        )

    return decorator
