"""Pure scene-authoring projections."""

from typing import Any

from cairn.domain.scenes import AuthoredScene

_AUTHORED_KEYS = ("atmosphere", "surface_details", "hidden", "secrets", "threads_in_air", "hooks_out")


def split_authored(raw: dict[str, Any]) -> AuthoredScene:
    """Pick the read-mostly authored bucket out of a raw scene dict."""
    return {key: raw[key] for key in _AUTHORED_KEYS if key in raw}  # type: ignore[return-value]
