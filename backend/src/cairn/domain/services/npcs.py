"""Pure NPC blueprint normalization."""

from typing import Any


def blueprint_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a seed/world-cast YAML blob into NPC constructor kwargs."""
    kwargs = dict(data)
    kwargs.setdefault("hp", kwargs.get("max_hp", 1))
    if "class" in kwargs:
        kwargs["class_"] = kwargs.pop("class")
    return kwargs
