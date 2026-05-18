from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from cairn.api.v1.schemas.characters import CharacterCreate, CharacterPatch

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.domain.exceptions import AuthError, ValidationError
from cairn.domain.services.ac import AcInput, derive_ac
from cairn.domain.services.leveling import SUBCLASS_LEVEL, initialize_resources
from cairn.srd import (
    get_armor,
    get_background,
    get_class,
    get_class_levels,
    get_proficiencies_for_race,
    get_race,
    get_subclass,
    get_subrace,
)
from cairn.types import AbilityScores, InventoryItem

log = structlog.get_logger()


def _modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


# Maps proficiency index prefixes → armor categories stored on the character.
_ARMOR_PROF_MAP: dict[str, list[str]] = {
    "all-armor": ["light", "medium", "heavy"],
    "light-armor": ["light"],
    "medium-armor": ["medium"],
    "heavy-armor": ["heavy"],
    "shields": ["shield"],
}

# Weapon proficiency categories — stored as-is (e.g. "simple", "martial").
# Specific weapon indices (e.g. "shortswords") are stored directly.
_WEAPON_CATEGORY_MAP: dict[str, str] = {
    "simple-weapons": "simple",
    "martial-weapons": "martial",
}


def _extract_proficiencies(
    cls_data: dict,
    race_index: str,
    subrace_index: str | None,
) -> tuple[list[str], list[str]]:
    """
    Return (armor_proficiencies, weapon_proficiencies) derived from class and race.

    Class proficiencies come from cls_data["proficiencies"].
    Race weapon proficiencies come from proficiencies.json (keyed by race/subrace).
    """
    armor_profs: list[str] = []
    weapon_profs: list[str] = []

    for p in cls_data.get("proficiencies", []):
        idx = p.get("index", "")
        if idx in _ARMOR_PROF_MAP:
            for cat in _ARMOR_PROF_MAP[idx]:
                if cat not in armor_profs:
                    armor_profs.append(cat)
        elif idx in _WEAPON_CATEGORY_MAP:
            cat = _WEAPON_CATEGORY_MAP[idx]
            if cat not in weapon_profs:
                weapon_profs.append(cat)
        elif idx.startswith("saving-throw-") or idx.startswith("skill-"):
            pass  # saves and skills handled separately
        elif idx and idx not in weapon_profs:
            # Specific weapon (e.g. "shortswords" for monk)
            weapon_profs.append(idx)

    # Race / subrace weapon proficiencies from proficiencies.json
    for p in get_proficiencies_for_race(race_index, subrace_index):
        if p.get("type") == "Weapons":
            idx = p.get("index", "")
            if idx and idx not in weapon_profs:
                weapon_profs.append(idx)

    return armor_profs, weapon_profs


def _build_inventory(cls_data: dict) -> list[InventoryItem]:
    """
    Build the starting inventory list. Items from starting_equipment get an
    srd_index field so the equip service can do reliable SRD lookups.
    Armor and shields are auto-equipped (first one found of each type).
    """
    inventory: list[InventoryItem] = []
    equipped_armor = False
    equipped_shield = False

    for entry in cls_data.get("starting_equipment", []):
        eq = entry.get("equipment", {})
        srd_index = eq.get("index", "")
        name = eq.get("name", srd_index)

        armor_data = get_armor(srd_index) if srd_index else None
        auto_equip = False
        if armor_data is not None:
            if armor_data.get("armor_category") == "Shield" and not equipped_shield:
                auto_equip = True
                equipped_shield = True
            elif armor_data.get("armor_category") != "Shield" and not equipped_armor:
                auto_equip = True
                equipped_armor = True

        inventory.append(
            {
                "name": name,
                "srd_index": srd_index,
                "quantity": entry.get("quantity", 1),
                "weight": 0,
                "notes": "",
                "equipped": auto_equip,
            }
        )

    return inventory


def _extract_skill_choices(cls_data: dict) -> tuple[int, list[str]]:
    """Return (num_required, allowed_skill_names) from class proficiency_choices."""
    total = 0
    allowed: list[str] = []
    for group in cls_data.get("proficiency_choices", []):
        opts = group.get("from", {}).get("options", [])
        skill_opts = [
            o["item"]["name"].replace("Skill: ", "")
            for o in opts
            if o.get("option_type") == "reference" and o.get("item", {}).get("index", "").startswith("skill-")
        ]
        if skill_opts:
            total += group.get("choose", 0)
            allowed.extend(skill_opts)
    return total, allowed


def _apply_ability_bonuses(scores: dict[str, int], bonuses: list[dict]) -> dict[str, int]:
    result = dict(scores)
    for b in bonuses:
        key = b["ability_score"]["index"]
        result[key] = result.get(key, 0) + b["bonus"]
    return result


def _build_spell_slots(level_data: dict) -> dict[str, int] | None:
    sc = level_data.get("spellcasting")
    if not sc:
        return None
    slots = {str(i): sc[f"spell_slots_level_{i}"] for i in range(1, 10) if sc.get(f"spell_slots_level_{i}", 0) > 0}
    return slots or None


async def create(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    body: CharacterCreate,
) -> Character:
    name = body.name
    race = body.race
    character_class = body.character_class
    background = body.background
    ability_scores = body.ability_scores
    skill_choices = body.skill_choices
    alignment = body.alignment
    bio = body.bio
    personality = body.personality
    voice_traits = body.voice_traits
    subrace = body.subrace
    subclass = body.subclass
    is_companion = body.is_companion
    spell_choices = body.spell_choices

    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)

    cls_data = get_class(character_class)
    if cls_data is None:
        raise ValidationError(f"unknown class: {character_class}")
    race_data = get_race(race)
    if race_data is None:
        raise ValidationError(f"unknown race: {race}")
    bg_data = get_background(background.lower().replace(" ", "-"))
    if bg_data is None:
        raise ValidationError(f"unknown background: {background}")

    subrace_data = None
    if subrace:
        subrace_data = get_subrace(subrace.lower().replace(" ", "-"))
        if subrace_data is None:
            raise ValidationError(f"unknown subrace: {subrace}")

    # Subclass: validate if provided, require for classes that pick at level 1
    if subclass is not None:
        sub_data = get_subclass(subclass.lower().replace(" ", "-"))
        if sub_data is None or sub_data.get("class", {}).get("index") != character_class:
            raise ValidationError(f"invalid subclass for {character_class}: {subclass!r}")
    if SUBCLASS_LEVEL.get(character_class) == 1 and not subclass:
        raise ValidationError(f"{character_class} requires subclass selection at character creation")

    # Validate skill choices against class options
    num_required, allowed = _extract_skill_choices(cls_data)
    if len(skill_choices) != num_required:
        raise ValidationError(f"{character_class} requires {num_required} skill choice(s), got {len(skill_choices)}")
    if len(set(skill_choices)) != len(skill_choices):
        raise ValidationError("duplicate skill choices are not allowed")
    invalid = [s for s in skill_choices if s not in allowed]
    if invalid:
        raise ValidationError(f"invalid skill choice(s) for {character_class}: {invalid}")

    # Derive stats from SRD
    hit_die_size: int = cls_data["hit_die"]
    saving_throw_proficiencies = [st["index"] for st in cls_data.get("saving_throws", [])]

    sc_info = cls_data.get("spellcasting")
    spellcasting_ability: str | None = sc_info["spellcasting_ability"]["index"] if sc_info else None

    class_levels = get_class_levels(character_class)
    level_data = class_levels[0] if class_levels else {}
    features = [{"index": f["index"], "name": f["name"]} for f in level_data.get("features", [])]
    spell_slots = _build_spell_slots(level_data)

    speed: int = race_data.get("speed", 30)
    race_traits = [{"index": t["index"], "name": t["name"]} for t in race_data.get("traits", [])]
    features = features + race_traits

    bg_skills: list[str] = bg_data.get("skill_proficiencies", [])
    tool_proficiencies: list[str] = bg_data.get("tool_proficiencies", [])
    skill_proficiencies = list(dict.fromkeys(skill_choices + bg_skills))

    final_scores = _apply_ability_bonuses(ability_scores, race_data.get("ability_bonuses", []))
    if subrace_data:
        final_scores = _apply_ability_bonuses(final_scores, subrace_data.get("ability_bonuses", []))

    con_mod = _modifier(final_scores.get("con", 10))
    max_hp = hit_die_size + con_mod
    dex_mod = _modifier(final_scores.get("dex", 10))
    wis_mod = _modifier(final_scores.get("wis", 10))
    has_perception = any(s.lower() == "perception" for s in skill_proficiencies)
    passive_perception = 10 + wis_mod + (2 if has_perception else 0)

    armor_proficiencies, weapon_proficiencies = _extract_proficiencies(cls_data, race, subrace)

    inventory = _build_inventory(cls_data)

    initial_ac = derive_ac(
        AcInput(
            id="new",
            ability_scores=cast(AbilityScores, final_scores),
            class_=character_class,
            inventory=inventory,
        )
    )

    log.info(
        "character_created",
        name=name,
        character_class=character_class,
        race=race,
        initial_ac=initial_ac,
        armor_proficiencies=armor_proficiencies,
        weapon_proficiencies=weapon_proficiencies,
    )

    return await character_queries.create_character(
        db,
        campaign_id=campaign_id,
        owner_id=owner_id,
        name=name,
        race=race,
        class_=character_class,
        subclass=subclass,
        background=background,
        alignment=alignment,
        level=1,
        xp=0,
        hp=max_hp,
        max_hp=max_hp,
        ac=initial_ac,
        speed=speed,
        hit_die_size=hit_die_size,
        hit_dice_remaining=1,
        ability_scores=final_scores,
        subrace=subrace,
        proficiency_bonus=2,
        initiative=dex_mod,
        passive_perception=passive_perception,
        saving_throw_proficiencies=saving_throw_proficiencies,
        skill_proficiencies=skill_proficiencies,
        tool_proficiencies=tool_proficiencies,
        armor_proficiencies=armor_proficiencies,
        weapon_proficiencies=weapon_proficiencies,
        spellcasting_ability=spellcasting_ability,
        spell_slots=spell_slots,
        spells_known=spell_choices or [],
        features=features,
        inventory=inventory,
        currency={"gp": 0, "sp": 0, "cp": 0},
        resources=initialize_resources(character_class, 1),
        is_companion=is_companion,
        bio=bio,
        personality=personality,
        voice_traits=voice_traits,
    )


async def patch(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    body: CharacterPatch,
) -> Character:
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)
    if char.is_companion:
        raise AuthError("cannot modify companion characters", code="forbidden")
    if body.name is not None:
        char.name = body.name
    if body.bio is not None:
        char.bio = body.bio
    await db.flush()
    return char


async def list_for_campaign(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> list[Character]:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await character_queries.list_characters_by_campaign(db, campaign_id)


async def delete(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    owner_id: str,
) -> None:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    await character_queries.delete_character(db, character_id)
