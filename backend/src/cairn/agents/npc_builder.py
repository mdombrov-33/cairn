"""NPC builder — generates a NarrativeProfile for an unauthored NPC on demand.

Two modes, tiered to value (see `llm/models.yaml`):
  - `build_background` (fast/cheap tier): the player addressed someone the world never
    named — a bartender, a guard. A tight `background` profile, generated just before
    dialogue streams so the wait is barely noticeable.
  - `deepen` (stronger tier): a one-time promotion pass fired when a `background` NPC has
    been genuinely engaged (≥3 exchanges). Extends the *existing* profile in place —
    same name, same established facts, more depth — so continuity is preserved.

The builder **never emits `major`** — plot-pillar figures are authored, not generated.
Canon context (location, area cast, always-on lore) is injected so a generated NPC does
not contradict the setting. Parse-fail safe: `build_background` degrades to a minimal
stub so dialogue can still proceed; `deepen` degrades to None so the caller keeps the
profile it already has.
"""

import structlog
from pydantic import BaseModel

from cairn.config import get_settings
from cairn.domain.exceptions import AgentError
from cairn.domain.services.narrative_profile import format_profile
from cairn.llm.client import complete_to_model
from cairn.llm.router import get_model
from cairn.prompts.registry import load_prompt, resolve_version
from cairn.types import NarrativeProfile

log = structlog.get_logger()


class _Voice(BaseModel):
    accent: str = ""
    pace: str = ""
    vocabulary: str = ""
    speech_quirks: list[str] = []


class _Goals(BaseModel):
    immediate: str = ""
    midterm: str = ""
    life: str = ""


class _Relationship(BaseModel):
    name: str = ""
    relation: str = ""
    status: str = ""
    notes: str = ""


class _Profile(BaseModel):
    name: str
    personality: str
    voice: _Voice = _Voice()
    race: str = ""
    age: int | None = None
    profession: str = ""
    physical: str = ""
    backstory: str = ""
    goals: _Goals = _Goals()
    prejudices: list[str] = []
    relationships: list[_Relationship] = []
    private_facts: list[str] = []


def _to_profile(p: _Profile) -> NarrativeProfile:
    """Structured output → the `NarrativeProfile` blob, dropping empty fields to keep it lean."""
    profile: NarrativeProfile = {
        "name": p.name,
        "personality": p.personality,
        "voice": {k: v for k, v in p.voice.model_dump().items() if v},  # type: ignore[typeddict-item]
    }
    if p.race:
        profile["race"] = p.race
    if p.age is not None:
        profile["age"] = p.age
    if p.profession:
        profile["profession"] = p.profession
    if p.physical:
        profile["physical"] = p.physical
    if p.backstory:
        profile["backstory"] = p.backstory
    goals = {k: v for k, v in p.goals.model_dump().items() if v}
    if goals:
        profile["goals"] = goals  # type: ignore[typeddict-item]
    if p.prejudices:
        profile["prejudices"] = p.prejudices
    rels = [{k: v for k, v in r.model_dump().items() if v} for r in p.relationships]
    rels = [r for r in rels if r]
    if rels:
        profile["relationships"] = rels  # type: ignore[typeddict-item]
    if p.private_facts:
        profile["private_facts"] = p.private_facts
    return profile


async def _generate(
    *,
    model_key: str,
    mode: str,
    tier: str,
    name: str,
    canon_context: str,
    existing_profile: str = "",
) -> _Profile:
    settings = get_settings()
    prompt = load_prompt("npc_builder", resolve_version("npc_builder", settings.llm_prompt_versions))
    model, fallbacks = get_model(model_key, settings.llm_env)
    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    mode=mode,
                    tier=tier,
                    name=name,
                    canon_context=canon_context,
                    existing_profile=existing_profile,
                ),
            }
        ],
        model_cls=_Profile,
        agent=model_key,
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )


async def build_background(*, name: str, canon_context: str) -> NarrativeProfile:
    """A tight `background` profile for a just-named NPC. Never fails — degrades to a stub."""
    try:
        result = await _generate(
            model_key="npc_builder", mode="background", tier="background", name=name, canon_context=canon_context
        )
    except AgentError:
        log.warning("npc_builder_background_parse_failed", name=name)
        return {"name": name, "personality": "An ordinary local, wary of strangers.", "voice": {}}
    return _to_profile(result)


async def deepen(*, existing_profile: NarrativeProfile, canon_context: str) -> NarrativeProfile | None:
    """One-time promotion deepen-pass. Returns None on failure so the caller keeps the old profile."""
    name = existing_profile.get("name", "")
    try:
        result = await _generate(
            model_key="npc_builder_deepen",
            mode="deepen",
            tier="recurring",
            name=name,
            canon_context=canon_context,
            existing_profile=format_profile(existing_profile),
        )
    except AgentError:
        log.warning("npc_builder_deepen_parse_failed", name=name)
        return None
    return _to_profile(result)
