import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.domain.exceptions import ValidationError
from cairn.srd import get_background, get_class, get_class_levels, get_race, get_subrace


def _modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


def _extract_skill_choices(cls_data: dict) -> tuple[int, list[str]]:
    """Return (num_required, allowed_skill_names) from class proficiency_choices."""
    total = 0
    allowed: list[str] = []
    for group in cls_data.get("proficiency_choices", []):
        opts = group.get("from", {}).get("options", [])
        skill_opts = [
            o["item"]["name"].replace("Skill: ", "")
            for o in opts
            if o.get("option_type") == "reference"
            and o.get("item", {}).get("index", "").startswith("skill-")
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
    slots = {
        str(i): sc[f"spell_slots_level_{i}"]
        for i in range(1, 10)
        if sc.get(f"spell_slots_level_{i}", 0) > 0
    }
    return slots or None


async def create(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    name: str,
    race: str,
    character_class: str,
    background: str,
    ability_scores: dict[str, int],
    skill_choices: list[str],
    ac: int,
    alignment: str,
    bio: str,
    personality: str,
    voice_traits: dict,
    subrace: str | None = None,
    subclass: str | None = None,
    is_companion: bool = False,
    spell_choices: list[str] | None = None,
) -> Character:
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

    # Validate skill choices against class options
    num_required, allowed = _extract_skill_choices(cls_data)
    if len(skill_choices) != num_required:
        raise ValidationError(
            f"{character_class} requires {num_required} skill choice(s), got {len(skill_choices)}"
        )
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

    inventory = [
        {
            "name": item["equipment"]["name"],
            "quantity": item.get("quantity", 1),
            "weight": 0,
            "notes": "",
            "equipped": False,
        }
        for item in cls_data.get("starting_equipment", [])
    ]

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
        ac=ac,
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
        spellcasting_ability=spellcasting_ability,
        spell_slots=spell_slots,
        spells_known=spell_choices or [],
        features=features,
        inventory=inventory,
        currency={"gp": 0, "sp": 0, "cp": 0},
        is_companion=is_companion,
        bio=bio,
        personality=personality,
        voice_traits=voice_traits,
    )


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
