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
from cairn.srd.catalog import catalog
from cairn.srd.models import AbilityBonus, ClassLevelRecord, ClassRecord
from cairn.types import AbilityScores, InventoryItem, NarrativeProfile

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
    cls_data: ClassRecord,
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

    for p in cls_data.proficiencies:
        idx = p.index
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
    for proficiency in catalog.proficiencies_for_race(race_index, subrace_index):
        if proficiency.type == "Weapons":
            idx = proficiency.index
            if idx and idx not in weapon_profs:
                weapon_profs.append(idx)

    return armor_profs, weapon_profs


def _build_inventory(cls_data: ClassRecord) -> list[InventoryItem]:
    """
    Build the starting inventory list. Items from starting_equipment get an
    srd_index field so the equip service can do reliable SRD lookups.
    Armor and shields are auto-equipped (first one found of each type).
    """
    inventory: list[InventoryItem] = []
    equipped_armor = False
    equipped_shield = False

    for entry in cls_data.starting_equipment:
        srd_index = entry.equipment.index
        name = entry.equipment.name

        armor_data = catalog.armor(srd_index)
        auto_equip = False
        if armor_data is not None:
            if armor_data.armor_category == "Shield" and not equipped_shield:
                auto_equip = True
                equipped_shield = True
            elif armor_data.armor_category != "Shield" and not equipped_armor:
                auto_equip = True
                equipped_armor = True

        inventory.append(
            {
                "name": name,
                "srd_index": srd_index,
                "quantity": entry.quantity,
                "weight": 0,
                "notes": "",
                "equipped": auto_equip,
            }
        )

    return inventory


def _extract_skill_choices(cls_data: ClassRecord) -> tuple[int, list[str]]:
    """Return (num_required, allowed_skill_names) from class proficiency_choices."""
    total = 0
    allowed: list[str] = []
    for group in cls_data.proficiency_choices:
        skill_opts = group.skill_names()
        if skill_opts:
            total += group.choose
            allowed.extend(skill_opts)
    return total, allowed


def _apply_ability_bonuses(scores: dict[str, int], bonuses: list[AbilityBonus]) -> dict[str, int]:
    result = dict(scores)
    for b in bonuses:
        key = b.ability_score.index
        result[key] = result.get(key, 0) + b.bonus
    return result


def _build_spell_slots(level_data: ClassLevelRecord | None) -> dict[str, int] | None:
    return level_data.spell_slots() if level_data else None


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
    narrative_profile = body.narrative_profile
    subrace = body.subrace
    subclass = body.subclass
    is_companion = body.is_companion
    spell_choices = body.spell_choices

    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)

    cls_data = catalog.class_(character_class)
    if cls_data is None:
        raise ValidationError(f"unknown class: {character_class}")
    race_data = catalog.race(race)
    if race_data is None:
        raise ValidationError(f"unknown race: {race}")
    bg_data = catalog.background(background)
    if bg_data is None:
        raise ValidationError(f"unknown background: {background}")

    subrace_data = None
    if subrace:
        subrace_data = catalog.subrace(subrace)
        if subrace_data is None:
            raise ValidationError(f"unknown subrace: {subrace}")

    # Subclass: validate if provided, require for classes that pick at level 1
    if subclass is not None:
        sub_data = catalog.subclass(subclass)
        if sub_data is None or sub_data.class_.index != character_class:
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
    hit_die_size = cls_data.hit_die
    saving_throw_proficiencies = [saving_throw.index for saving_throw in cls_data.saving_throws]

    spellcasting_ability = (
        cls_data.spellcasting.spellcasting_ability.index
        if cls_data.spellcasting and cls_data.spellcasting.spellcasting_ability
        else None
    )

    class_levels = catalog.class_levels(character_class)
    level_data = class_levels[0] if class_levels else None
    features = [
        {"index": feature.index, "name": feature.name} for feature in (level_data.features if level_data else [])
    ]
    spell_slots = _build_spell_slots(level_data)

    speed = race_data.speed
    race_traits = [{"index": trait.index, "name": trait.name} for trait in race_data.traits]
    subrace_traits = (
        [{"index": trait.index, "name": trait.name} for trait in subrace_data.racial_traits] if subrace_data else []
    )
    if any(trait["index"] == "fleet-of-foot" for trait in subrace_traits):
        speed += 5
    features = features + race_traits + subrace_traits

    bg_skills = bg_data.skill_proficiencies
    tool_proficiencies = bg_data.tool_proficiencies
    skill_proficiencies = list(dict.fromkeys(skill_choices + bg_skills))

    final_scores = _apply_ability_bonuses(ability_scores, race_data.ability_bonuses)
    if subrace_data:
        final_scores = _apply_ability_bonuses(final_scores, subrace_data.ability_bonuses)

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
        classes=[{"name": character_class, "level": 1, "hit_dice_spent": 0, "subclass": subclass}],
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
        resources=initialize_resources(character_class, 1, final_scores),
        is_companion=is_companion,
        narrative_profile=narrative_profile,
        companion_meta=(
            {"approval": 0, "mood": "content", "personal_goal": "", "secret": None, "approval_log": []}
            if is_companion
            else None
        ),
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
    if body.narrative_profile is not None:
        char.narrative_profile = cast(NarrativeProfile, body.narrative_profile)
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
