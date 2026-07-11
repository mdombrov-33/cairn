"""Generate a compact theater-of-mind battlefield from the current scene."""

import json
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from cairn.domain.combat import CombatZone, ZoneSeed
from cairn.domain.exceptions import AgentError, LLMError
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup

log = structlog.get_logger()


class _Zone(BaseModel):
    id: str
    name: str
    description: str
    cover: str = "none"
    cover_ac_bonus: int = 0
    cover_save_bonus: int = 0
    difficult_terrain: bool = False
    hazard: str | None = None
    distances: dict[str, Literal["close", "far"]] = Field(default_factory=dict)


class _ZoneSeed(BaseModel):
    zones: list[_Zone] = Field(min_length=3, max_length=6)
    player_start: str
    enemy_start: str


async def run(*, location_name: str, location_description: str, scene: dict) -> ZoneSeed | None:
    """Return a generated battlefield, or None when generation cannot be parsed."""
    prompt, model, fallbacks = agent_setup("zone_seeder")
    try:
        result = await complete_to_model(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt.render(
                        location_name=location_name,
                        location_description=location_description,
                        scene=json.dumps(scene, indent=2),
                    ),
                }
            ],
            model_cls=_ZoneSeed,
            agent="zone_seeder",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except (AgentError, LLMError) as exc:
        log.warning("zone_seeder_failed", location=location_name, error=str(exc))
        return None

    zones: list[CombatZone] = [
        {
            "id": zone.id,
            "name": zone.name,
            "description": zone.description,
            "cover": zone.cover,
            "cover_ac_bonus": zone.cover_ac_bonus,
            "cover_save_bonus": zone.cover_save_bonus,
            "difficult_terrain": zone.difficult_terrain,
            "hazard": zone.hazard,
            "distances": zone.distances,
        }
        for zone in result.zones
    ]
    return {"zones": zones, "player_start": result.player_start, "enemy_start": result.enemy_start}
