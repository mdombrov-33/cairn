import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import npc_builder
from cairn.db.models.npc import NPC
from cairn.db.models.scene import Scene
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import worlds as world_queries
from cairn.domain.services import campaign_view

# A background NPC the party keeps returning to promotes to `recurring` at this many exchanges.
DIALOGUE_PROMOTION_THRESHOLD = 3

_SEED_DIR = Path(__file__).parent.parent.parent / "seed" / "worlds"


async def list_by_campaign(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> list[NPC]:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await npc_queries.get_npcs_by_campaign(db, campaign_id)


async def get(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    owner_id: str,
) -> NPC:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await npc_queries.get_npc(db, npc_id)


def _blueprint_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a seed/world-cast YAML blob into NPC constructor kwargs."""
    kwargs = dict(data)
    kwargs.setdefault("hp", kwargs.get("max_hp", 1))
    if "class" in kwargs:
        kwargs["class_"] = kwargs.pop("class")
    return kwargs


async def create_from_blueprint(db: AsyncSession, campaign_id: uuid.UUID, data: dict[str, Any]) -> NPC:
    """Clone an authored character blueprint (scenario or world cast) into a campaign NPC row."""
    return await npc_queries.create_npc(db, campaign_id=campaign_id, **_blueprint_kwargs(data))


async def build_canon_context(db: AsyncSession, campaign_id: uuid.UUID, scene: Scene | None) -> str:
    """The setting facts a generated NPC must not contradict: where they are, who else is here,
    and the always-on world lore. Key-match pre-RAG (Slice 13 swaps in relevance retrieval)."""
    parts: list[str] = []

    if scene is not None and scene.location_id is not None:
        location = await location_queries.get_location(db, scene.location_id)
        if location is not None:
            parts.append(f"Location: {location.name} — {location.description}")
        area = await npc_queries.list_by_location(db, campaign_id, scene.location_id)
        if area:
            parts.append("People already here: " + ", ".join(n.name for n in area))

    _, _, world = await campaign_view.world_chain(db, campaign_id)
    chunks = await world_queries.list_lore_chunks(db, world.id, always_on_only=True)
    if chunks:
        parts.append("World facts:\n" + "\n".join(f"- {c.title}: {c.content}" for c in chunks))

    return "\n\n".join(parts)


async def instantiate_world_cast(db: AsyncSession, *, campaign_id: uuid.UUID, world_key: str, name: str) -> NPC | None:
    """Lazily bring an authored world-cast figure into the campaign on first encounter.

    The scenario didn't connect this figure at creation, but the player has now reached them —
    so instantiate from the canon blueprint (preserving their authored depth and tier) rather
    than generating someone new. Returns None if no world figure matches the spoken name.
    """
    char_dir = _SEED_DIR / world_key / "characters"
    if not char_dir.exists():
        return None
    hint = name.strip().lower()
    if not hint:
        return None
    for path in sorted(char_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        bp_name = str(data.get("name", "")).strip().lower()
        if bp_name and (hint in bp_name or bp_name in hint):
            return await create_from_blueprint(db, campaign_id, data)
    return None


async def generate_background_npc(db: AsyncSession, *, campaign_id: uuid.UUID, name: str, scene: Scene | None) -> NPC:
    """Lazily generate a `background` NPC the player just addressed but no one authored."""
    canon = await build_canon_context(db, campaign_id, scene)
    profile = await npc_builder.build_background(name=name, canon_context=canon)
    return await npc_queries.create_npc(
        db,
        campaign_id=campaign_id,
        name=profile["name"],
        narrative_profile=profile,
        tier="background",
        disposition="neutral",
        location_id=scene.location_id if scene is not None else None,
    )


async def record_dialogue_exchange(db: AsyncSession, *, npc: NPC, scene: Scene | None) -> None:
    """Count a dialogue exchange with an NPC and auto-promote it once the party is invested.

    At the threshold a `background` NPC becomes `recurring` and gets a one-time deepen-pass
    (stronger model) that extends its profile in place — established facts preserved.
    """
    count = await npc_queries.bump_dialogue_exchange(db, npc)
    if npc.tier != "background" or count < DIALOGUE_PROMOTION_THRESHOLD:
        return

    canon = await build_canon_context(db, npc.campaign_id, scene)
    deepened = await npc_builder.deepen(existing_profile=npc.narrative_profile, canon_context=canon)
    if deepened is not None:
        npc.narrative_profile = deepened
    npc.tier = "recurring"
    await db.flush()
