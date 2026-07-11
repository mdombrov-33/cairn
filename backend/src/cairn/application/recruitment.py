"""Recruitment — the NPC↔Character bridge.

An unrecruited companion lives in the world as an ordinary NPC. Recruiting converts it into a
`Character(is_companion=True)` with a full playable sheet (so `ally_ai` can actually spend its
abilities); dismissing reverses the trip, dropping the parted companion back into the world as an
NPC at the current location. One path serves both predefined recruits (an authored
`companion_sheet` ships on the blueprint) and dynamic ones (any bonded `recurring` NPC — the sheet
is derived from the NPC's own stats). The `recruiter` agent adjudicates the bid; this module only
performs the conversions and enforces the soft party cap.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries

# Soft cap — recruiting past it requires dismissing someone first (narrated, not a hard wall).
MAX_ACTIVE_COMPANIONS = 4


# A newly recruited NPC can be asked to join if it's a predefined companion or a bonded recurring
# presence. A plain `background` walk-on has to promote (≥3 exchanges) before it's eligible.
def is_recruitable(npc: NPC) -> bool:
    return npc.recruitable or npc.tier == "recurring"


def _companion_meta(personal_goal: str = "", secret: str | None = None) -> dict[str, Any]:
    return {"approval": 0, "mood": "content", "personal_goal": personal_goal, "secret": secret, "approval_log": []}


def _identity(npc: NPC) -> dict[str, Any]:
    return {
        "name": npc.name,
        "race": npc.race or "human",
        "background": npc.background or "wanderer",
        "alignment": npc.alignment,
        "level": npc.level,
    }


def _from_sheet(npc: NPC) -> tuple[dict[str, Any], dict[str, Any]]:
    """Predefined recruit: copy the authored `companion_sheet` verbatim, init approval fresh."""
    sheet = dict(npc.companion_sheet or {})
    meta = _companion_meta(sheet.pop("personal_goal", ""), sheet.pop("secret", None))
    return {**_identity(npc), **sheet}, meta


def _from_npc_stats(npc: NPC) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dynamic recruit: derive a playable sheet straight from the NPC's own columns and profile.

    The NPC row already carries the full combat stat block, so no LLM stat-up is needed — a
    deterministic copy is both simpler and mechanically consistent. Companion-only bits the NPC
    lacks (hit dice, personal goal, secret) are seeded from sane defaults / the narrative profile.
    """
    profile = npc.narrative_profile or {}
    goals = profile.get("goals") or {}
    personal_goal = goals.get("life") or goals.get("midterm") or ""
    facts = profile.get("private_facts") or []
    meta = _companion_meta(personal_goal, facts[0] if facts else None)

    kwargs = {
        **_identity(npc),
        "classes": [
            {"name": npc.class_ or "commoner", "level": npc.level, "hit_dice_spent": 0, "subclass": npc.subclass}
        ],
        "hit_die_size": 8,
        "hit_dice_remaining": npc.level,
        "hp": npc.hp,
        "max_hp": npc.max_hp,
        "temp_hp": npc.temp_hp,
        "ac": npc.ac,
        "speed": npc.speed,
        "proficiency_bonus": npc.proficiency_bonus,
        "initiative": npc.initiative,
        "passive_perception": npc.passive_perception,
        "ability_scores": npc.ability_scores,
        "saving_throw_proficiencies": npc.saving_throw_proficiencies,
        "skill_proficiencies": npc.skill_proficiencies,
        "tool_proficiencies": npc.tool_proficiencies,
        "armor_proficiencies": npc.armor_proficiencies,
        "weapon_proficiencies": npc.weapon_proficiencies,
        "spellcasting_ability": npc.spellcasting_ability,
        "spell_slots": npc.spell_slots,
        "spells_known": npc.spells_known,
        "features": npc.features,
        "feats": npc.feats,
        "inventory": npc.inventory,
        "currency": npc.currency,
    }
    return kwargs, meta


async def active_companion_count(db: AsyncSession, campaign_id: uuid.UUID) -> int:
    chars = await character_queries.list_characters_by_campaign(db, campaign_id)
    return sum(1 for c in chars if c.is_companion and c.status == "active")


async def is_party_full(db: AsyncSession, campaign_id: uuid.UUID) -> bool:
    return await active_companion_count(db, campaign_id) >= MAX_ACTIVE_COMPANIONS


async def recruit(db: AsyncSession, *, npc: NPC, owner_id: str) -> Character:
    """Convert an NPC into a party companion and retire the source NPC row."""
    kwargs, meta = _from_sheet(npc) if npc.companion_sheet else _from_npc_stats(npc)
    character = await character_queries.create_character(
        db,
        campaign_id=npc.campaign_id,
        owner_id=owner_id,
        is_companion=True,
        status="active",
        narrative_profile=npc.narrative_profile,
        companion_meta=meta,
        **kwargs,
    )
    await npc_queries.delete_npc(db, npc.id)
    return character


def _disposition_from_approval(approval: int) -> str:
    if approval >= 15:
        return "friendly"
    if approval <= -15:
        return "hostile"
    return "neutral"


async def dismiss(db: AsyncSession, *, character: Character, location_id: uuid.UUID | None) -> NPC:
    """Part ways with a companion: convert it back into a full-strength NPC at the current location,
    disposition carried from where the relationship stood, and retire the Character row."""
    meta = character.companion_meta or {}
    npc = await npc_queries.create_npc(
        db,
        campaign_id=character.campaign_id,
        name=character.name,
        class_=character.class_name or None,
        subclass=character.subclass_name,
        race=character.race,
        background=character.background,
        alignment=character.alignment,
        level=character.level,
        narrative_profile=character.narrative_profile,
        disposition=_disposition_from_approval(meta.get("approval", 0)),
        tier="recurring",
        recruitable=True,
        location_id=location_id,
        ac=character.ac,
        max_hp=character.max_hp,
        hp=character.hp,
        temp_hp=character.temp_hp,
        speed=character.speed,
        proficiency_bonus=character.proficiency_bonus,
        initiative=character.initiative,
        passive_perception=character.passive_perception,
        ability_scores=character.ability_scores,
        saving_throw_proficiencies=character.saving_throw_proficiencies,
        skill_proficiencies=character.skill_proficiencies,
        tool_proficiencies=character.tool_proficiencies,
        armor_proficiencies=character.armor_proficiencies,
        weapon_proficiencies=character.weapon_proficiencies,
        spellcasting_ability=character.spellcasting_ability,
        spell_slots=character.spell_slots,
        spells_known=character.spells_known,
        features=character.features,
        feats=character.feats,
        inventory=character.inventory,
        currency=character.currency,
    )
    await character_queries.delete_character(db, character.id)
    return npc
