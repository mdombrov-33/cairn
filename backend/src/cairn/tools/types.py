"""Tool-boundary value types."""

from typing import Annotated

type ToolUUID = Annotated[str, "UUID as string — converted at the tool boundary"]
