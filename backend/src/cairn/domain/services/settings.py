"""Validate, resolve, and serialize the one campaign-settings snapshot per turn."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

type CampaignPreset = Literal["narrative", "balanced", "tactical"]
type CompanionControl = Literal["ai", "suggest", "player"]
type CompanionManagementControl = Literal["ai", "player"]
type PassiveCheckVisibility = Literal["silent", "surfaced", "on_demand"]
type DeathMode = Literal["hardcore", "narrative", "pacifist"]
type ContentLevel = Literal["off", "fade", "on"]
type NarrationVerbosity = Literal["terse", "normal", "lush"]


class _SettingsModel(BaseModel):
    """The strict, immutable model contract for the settings seam."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class _SparseSettingsModel(_SettingsModel):
    @model_validator(mode="before")
    @classmethod
    def _reject_nulls(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        values = cast(Mapping[str, object], value)
        if any(item is None for item in values.values()):
            raise ValueError("settings overrides cannot contain null")
        return values


class CompanionOverrides(_SparseSettingsModel):
    combat: CompanionControl | None = None
    dialogue: CompanionControl | None = None
    equipment: CompanionManagementControl | None = None
    leveling: CompanionManagementControl | None = None
    checks: CompanionManagementControl | None = None


class CheckOverrides(_SparseSettingsModel):
    passive_perception: PassiveCheckVisibility | None = None
    passive_insight: PassiveCheckVisibility | None = None


class ContentOverrides(_SparseSettingsModel):
    violence: ContentLevel | None = None
    gore: ContentLevel | None = None
    sexual: ContentLevel | None = None
    romance: ContentLevel | None = None
    horror: ContentLevel | None = None
    substances: ContentLevel | None = None
    lines: tuple[str, ...] | None = None
    tone_note: str | None = None

    @field_validator("lines", mode="before")
    @classmethod
    def _freeze_lines(cls, value: Any) -> Any:
        return tuple(cast(list[str], value)) if isinstance(value, list) else value


class NarrationOverrides(_SparseSettingsModel):
    verbosity: NarrationVerbosity | None = None


class CampaignSettingsOverrides(_SparseSettingsModel):
    companion: CompanionOverrides | None = None
    checks: CheckOverrides | None = None
    death_mode: DeathMode | None = None
    content: ContentOverrides | None = None
    narration: NarrationOverrides | None = None

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class StoredCampaignSettings(_SettingsModel):
    """The sparse JSONB representation persisted on ``Campaign.settings``."""

    preset: CampaignPreset = "narrative"
    overrides: CampaignSettingsOverrides = CampaignSettingsOverrides()

    def as_json(self) -> dict[str, Any]:
        return {"preset": self.preset, "overrides": self.overrides.as_json()}


class CompanionSettings(_SettingsModel):
    combat: CompanionControl = "ai"
    dialogue: CompanionControl = "ai"
    equipment: CompanionManagementControl = "ai"
    leveling: CompanionManagementControl = "ai"
    checks: CompanionManagementControl = "ai"


class CheckSettings(_SettingsModel):
    passive_perception: PassiveCheckVisibility = "silent"
    passive_insight: PassiveCheckVisibility = "silent"


class ContentSettings(_SettingsModel):
    violence: ContentLevel = "fade"
    gore: ContentLevel = "fade"
    sexual: ContentLevel = "fade"
    romance: ContentLevel = "fade"
    horror: ContentLevel = "fade"
    substances: ContentLevel = "fade"
    lines: tuple[str, ...] = ()
    tone_note: str = ""

    @field_validator("lines", mode="before")
    @classmethod
    def _freeze_lines(cls, value: Any) -> Any:
        return tuple(cast(list[str], value)) if isinstance(value, list) else value


class NarrationSettings(_SettingsModel):
    verbosity: NarrationVerbosity = "normal"


class ResolvedCampaignSettings(_SettingsModel):
    """The complete immutable settings snapshot bound for one turn."""

    preset: CampaignPreset = "narrative"
    companion: CompanionSettings = CompanionSettings()
    checks: CheckSettings = CheckSettings()
    death_mode: DeathMode = "narrative"
    content: ContentSettings = ContentSettings()
    narration: NarrationSettings = NarrationSettings()

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


_PRESETS: dict[CampaignPreset, CampaignSettingsOverrides] = {
    "narrative": CampaignSettingsOverrides(),
    "balanced": CampaignSettingsOverrides(
        companion=CompanionOverrides(combat="suggest"),
        checks=CheckOverrides(passive_perception="surfaced", passive_insight="surfaced"),
    ),
    "tactical": CampaignSettingsOverrides(
        companion=CompanionOverrides(combat="player", equipment="player", leveling="player", checks="player"),
        checks=CheckOverrides(passive_perception="surfaced", passive_insight="surfaced"),
        death_mode="hardcore",
    ),
}


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], cast(Mapping[str, Any], value))
        else:
            base[key] = value
    return base


def parse_stored_settings(stored: Mapping[str, Any] | StoredCampaignSettings | None) -> StoredCampaignSettings:
    if isinstance(stored, StoredCampaignSettings):
        return stored
    return StoredCampaignSettings.model_validate(stored or {})


def parse_overrides(overrides: Mapping[str, Any] | CampaignSettingsOverrides) -> CampaignSettingsOverrides:
    if isinstance(overrides, CampaignSettingsOverrides):
        return overrides
    return CampaignSettingsOverrides.model_validate(overrides)


def validate_overrides(overrides: Mapping[str, Any] | CampaignSettingsOverrides) -> None:
    """Validate a sparse override at the HTTP/persistence seam."""
    if isinstance(overrides, Mapping):
        unknown = set(overrides) - {"companion", "checks", "death_mode", "content", "narration"}
        if unknown:
            raise ValueError(f"unknown settings override: {sorted(unknown)[0]}")
    parse_overrides(overrides)


def merge_overrides(
    current: Mapping[str, Any] | CampaignSettingsOverrides,
    patch: Mapping[str, Any] | CampaignSettingsOverrides,
) -> CampaignSettingsOverrides:
    """Deep-merge sparse settings without exposing merge mechanics to callers."""
    merged = _deep_merge(parse_overrides(current).as_json(), parse_overrides(patch).as_json())
    return CampaignSettingsOverrides.model_validate(merged)


def resolve_settings(stored: Mapping[str, Any] | StoredCampaignSettings | None) -> ResolvedCampaignSettings:
    """Return the typed defaults, named preset, and sparse overrides for one turn."""
    parsed = parse_stored_settings(stored)
    resolved = ResolvedCampaignSettings().as_json()
    _deep_merge(resolved, _PRESETS[parsed.preset].as_json())
    _deep_merge(resolved, parsed.overrides.as_json())
    resolved["preset"] = parsed.preset
    return ResolvedCampaignSettings.model_validate(resolved)
