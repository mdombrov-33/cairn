"""Resolve the one campaign-settings snapshot every turn consumes."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_CONTENT_KEYS = ("violence", "gore", "sexual", "romance", "horror", "substances")

_BASE: dict[str, Any] = {
    "preset": "narrative",
    "companion": {
        "combat": "ai",
        "dialogue": "ai",
        "equipment": "ai",
        "leveling": "ai",
        "checks": "ai",
    },
    "checks": {"passive_perception": "silent", "passive_insight": "silent"},
    "death_mode": "narrative",
    "content": {**{key: "fade" for key in _CONTENT_KEYS}, "lines": [], "tone_note": ""},
    "narration": {"verbosity": "normal"},
}

_PRESETS: dict[str, dict[str, Any]] = {
    "narrative": {},
    "balanced": {
        "companion": {"combat": "suggest"},
        "checks": {"passive_perception": "surfaced", "passive_insight": "surfaced"},
    },
    "tactical": {
        "companion": {"combat": "player", "equipment": "player", "leveling": "player", "checks": "player"},
        "checks": {"passive_perception": "surfaced", "passive_insight": "surfaced"},
        "death_mode": "hardcore",
    },
}


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def validate_overrides(overrides: Mapping[str, Any]) -> None:
    """Reject unknown keys and values before they can enter the sparse stored layer."""
    allowed = {"companion", "checks", "death_mode", "content", "narration"}
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"unknown settings override: {sorted(unknown)[0]}")

    companion = overrides.get("companion", {})
    if not isinstance(companion, Mapping):
        raise ValueError("companion overrides must be an object")
    companion_values = {
        "combat": {"ai", "suggest", "player"},
        "dialogue": {"ai", "suggest", "player"},
        "equipment": {"ai", "player"},
        "leveling": {"ai", "player"},
        "checks": {"ai", "player"},
    }
    _validate_enum_block("companion", companion, companion_values)

    checks = overrides.get("checks", {})
    if not isinstance(checks, Mapping):
        raise ValueError("checks overrides must be an object")
    _validate_enum_block(
        "checks",
        checks,
        {
            "passive_perception": {"silent", "surfaced", "on_demand"},
            "passive_insight": {"silent", "surfaced", "on_demand"},
        },
    )

    if "death_mode" in overrides and overrides["death_mode"] not in {"hardcore", "narrative", "pacifist"}:
        raise ValueError("death_mode must be hardcore, narrative, or pacifist")

    content = overrides.get("content", {})
    if not isinstance(content, Mapping):
        raise ValueError("content overrides must be an object")
    allowed_content = {*_CONTENT_KEYS, "lines", "tone_note"}
    if set(content) - allowed_content:
        raise ValueError("unknown content override")
    for key in _CONTENT_KEYS:
        if key in content and content[key] not in {"off", "fade", "on"}:
            raise ValueError(f"content.{key} must be off, fade, or on")
    if "lines" in content and (
        not isinstance(content["lines"], list) or not all(isinstance(x, str) for x in content["lines"])
    ):
        raise ValueError("content.lines must be a list of strings")
    if "tone_note" in content and not isinstance(content["tone_note"], str):
        raise ValueError("content.tone_note must be a string")

    narration = overrides.get("narration", {})
    if not isinstance(narration, Mapping):
        raise ValueError("narration overrides must be an object")
    _validate_enum_block("narration", narration, {"verbosity": {"terse", "normal", "lush"}})


def merge_overrides(current: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge a validated sparse patch without exposing merge mechanics to callers."""
    return _deep_merge(deepcopy(dict(current)), patch)


def _validate_enum_block(name: str, value: Mapping[str, Any], allowed: Mapping[str, set[str]]) -> None:
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {name} override: {sorted(unknown)[0]}")
    for key, options in allowed.items():
        if key in value and value[key] not in options:
            raise ValueError(f"{name}.{key} has an invalid value")


def resolve_settings(stored: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return base defaults + named preset + sparse overrides as one ready-to-use snapshot."""
    stored = stored or {}
    preset = stored.get("preset", "narrative")
    if preset not in _PRESETS:
        preset = "narrative"
    overrides = stored.get("overrides", {})
    if not isinstance(overrides, Mapping):
        overrides = {}

    resolved = _deep_merge(deepcopy(_BASE), _PRESETS[preset])
    _deep_merge(resolved, overrides)
    resolved["preset"] = preset
    return resolved
