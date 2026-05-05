import math
import random
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError, NotFoundError


def _roll_die(sides: int) -> int:
    return random.randint(1, sides)


def _parse_and_roll(expression: str) -> int:
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    return sum(_roll_die(sides) for _ in range(count)) + modifier


def _dex_mod(score: int) -> int:
    return math.floor((score - 10) / 2)


async def start(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    enemies: list[dict],
) -> dict:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)

    if db_session.combat_active:
        raise ConflictError("combat is already active for this session", code="combat_active")

    combatants: list[dict] = []

    # Enroll party
    characters = await party_queries.get_party(db, session_id)
    for char in characters:
        combatants.append(
            {
                "id": str(char.id),
                "type": "character",
                "name": char.name,
                "initiative_roll": random.randint(1, 20) + char.initiative,
                "initiative_modifier": char.initiative,
                "zone": None,
                "conditions": list(char.conditions),
                "is_alive": char.hp > 0,
                "is_conscious": char.hp > 0,
            }
        )

    # Enroll enemies
    for enemy in enemies:
        if enemy["type"] == "npc":
            npc = await npc_queries.get_npc(db, uuid.UUID(str(enemy["id"])))
            combatants.append(
                {
                    "id": str(npc.id),
                    "type": "npc",
                    "name": npc.name,
                    "initiative_roll": random.randint(1, 20) + npc.initiative,
                    "initiative_modifier": npc.initiative,
                    "zone": None,
                    "conditions": list(npc.conditions),
                    "is_alive": npc.hp > 0,
                    "is_conscious": npc.hp > 0,
                }
            )

        elif enemy["type"] == "monster":
            monster = rules.get_monster(enemy["name"])
            if monster is None:
                raise NotFoundError(
                    f"monster '{enemy['name']}' not found in SRD", code="monster_not_found"
                )  # noqa: E501

            dex = _dex_mod(monster.get("dexterity", 10))
            ac = monster["armor_class"][0]["value"] if monster.get("armor_class") else 10
            count = max(1, enemy.get("count", 1))

            for i in range(count):
                max_hp = _parse_and_roll(monster["hit_points_roll"])
                label = monster["name"] if count == 1 else f"{monster['name']} {i + 1}"
                combatants.append(
                    {
                        "id": f"monster-{uuid.uuid4()}",
                        "type": "monster",
                        "name": label,
                        "srd_index": monster["index"],
                        "initiative_roll": random.randint(1, 20) + dex,
                        "initiative_modifier": dex,
                        "zone": None,
                        "hp": max_hp,
                        "max_hp": max_hp,
                        "ac": ac,
                        "conditions": [],
                        "is_alive": True,
                        "is_conscious": True,
                        "actions": monster.get("actions", []),
                        "special_abilities": monster.get("special_abilities", []),
                    }
                )

    combatants.sort(
        key=lambda c: (c["initiative_roll"], c["initiative_modifier"], random.random()),
        reverse=True,
    )

    combat_state = {"round": 1, "turn_index": 0, "combatants": combatants}
    await session_queries.update_combat_state(
        db, session_id, combat_state=combat_state, combat_active=True
    )
    await db.commit()
    return combat_state


async def end(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    outcome: str,
) -> None:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)

    if not db_session.combat_active:
        raise ConflictError("no active combat for this session", code="combat_not_active")

    await session_queries.update_combat_state(
        db, session_id, combat_state=None, combat_active=False
    )
    await db.commit()


async def get_state(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
) -> dict:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return {"combat_active": db_session.combat_active, "combat_state": db_session.combat_state}
