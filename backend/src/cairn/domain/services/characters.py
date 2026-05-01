import math
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries


def _proficiency_bonus(level: int) -> int:
    return (level - 1) // 4 + 2


def _modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


async def create(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    name: str,
    race: str,
    character_class: str,
    background: str,
    level: int,
    stats: dict[str, int],
    hp: int,
    max_hp: int,
    ac: int,
    speed: int = 30,
    saving_throw_proficiencies: list[str],
    skill_proficiencies: list[str],
    spellcasting_ability: str | None = None,
    spell_slots: dict[str, Any] | None = None,
    spells_known: list[str],
    features: list[str],
    inventory: list[Any],
    currency: dict[str, int],
    alignment: str | None = None,
    subclass: str | None = None,
) -> Character:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)

    prof_bonus = _proficiency_bonus(level)
    dex_mod = _modifier(stats.get("dex", 10))
    wis_mod = _modifier(stats.get("wis", 10))
    has_perception = "perception" in skill_proficiencies
    passive_perception = 10 + wis_mod + (prof_bonus if has_perception else 0)

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
        level=level,
        xp=0,
        hp=hp,
        max_hp=max_hp,
        ac=ac,
        speed=speed,
        stats=stats,
        proficiency_bonus=prof_bonus,
        initiative=dex_mod,
        passive_perception=passive_perception,
        saving_throw_proficiencies=saving_throw_proficiencies,
        skill_proficiencies=skill_proficiencies,
        spellcasting_ability=spellcasting_ability,
        spell_slots=spell_slots,
        spells_known=spells_known,
        features=features,
        inventory=inventory,
        currency=currency,
    )


async def get_for_campaign(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> Character:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await character_queries.get_character_by_campaign(db, campaign_id)
