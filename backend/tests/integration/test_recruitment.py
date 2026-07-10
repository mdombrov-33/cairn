"""Integration tests for Phase 5 — recruitment flow.

The `recruiter` adjudication (the LLM decision) is stubbed; these lock the wiring around it:
NPC→Character conversion (predefined sheet + dynamic stat-up), the accept/refuse/conditional
branches, the soft party cap, eligibility gating, and dismissal back to an NPC.
"""

import uuid
from typing import Literal
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.agents.recruiter import RecruitDecision
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.domain.services import recruitment
from cairn.domain.services.settings import ResolvedCampaignSettings
from cairn.pipelines.turn_graph import TurnState, _resolve_dismissal, _resolve_recruitment
from tests._factories import make_campaign, make_character, make_session

_COMPANION_PROFILE = {"name": "Ally", "personality": "Steadfast.", "voice": {}}


def _state(campaign_id: str, intent: str, npc_name: str) -> TurnState:
    return {
        "session_id": str(uuid.uuid4()),
        "campaign_id": campaign_id,
        "player_input": f"I ask {npc_name} to join us.",
        "intent": intent,
        "npc_name": npc_name,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": None,
        "is_scene_entry": False,
        "combat_just_started": False,
        "settings": ResolvedCampaignSettings(),
    }


def _decision(kind: Literal["accept", "refuse", "conditional"], line: str = "...", condition: str = "") -> AsyncMock:
    return AsyncMock(return_value=RecruitDecision(decision=kind, line=line, condition=condition))


async def _find_npc(campaign_id: str, name: str):
    async with db_client.get_session() as db:
        return await npc_queries.find_by_name(db, uuid.UUID(campaign_id), name)


async def _companions(campaign_id: str):
    async with db_client.get_session() as db:
        chars = await character_queries.list_characters_by_campaign(db, uuid.UUID(campaign_id))
    return [c for c in chars if c.is_companion]


async def test_recruit_predefined_converts_npc_using_sheet(client: AsyncClient) -> None:
    camp = await make_campaign(client)  # tavern_v1 seeds Bram Ashford (recurring, recruitable + sheet)
    await make_session(client, camp["id"])

    with patch("cairn.pipelines.turn_graph.recruiter.run", new=_decision("accept", "Aye — I'm with you.")):
        out = await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Bram"))

    assert "joins the party" in out["npc_context"]
    assert await _find_npc(camp["id"], "Bram") is None  # source NPC retired

    companions = await _companions(camp["id"])
    bram = next(c for c in companions if "Bram" in c.name)
    assert bram.is_companion and bram.max_hp == 20 and bram.ac == 16  # authored sheet copied
    assert bram.companion_meta["approval"] == 0
    assert bram.companion_meta["personal_goal"]  # seeded from the sheet


async def test_recruit_refuse_keeps_npc(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    with patch("cairn.pipelines.turn_graph.recruiter.run", new=_decision("refuse", "Not a chance.")):
        out = await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Bram"))

    assert out["npc_context"] == '[Bram Ashford]: "Not a chance."'
    assert await _find_npc(camp["id"], "Bram") is not None  # still an NPC
    assert await _companions(camp["id"]) == []


async def test_recruit_conditional_records_condition(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    with patch(
        "cairn.pipelines.turn_graph.recruiter.run",
        new=_decision("conditional", "Prove it first.", condition="clear the crows off the north road"),
    ):
        await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Bram"))

    npc = await _find_npc(camp["id"], "Bram")
    assert npc is not None
    assert npc.recruitment_condition == "clear the crows off the north road"


async def test_recruit_dynamic_stats_up_from_npc_columns(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = uuid.UUID(camp["id"])
    async with db_client.get_session() as db:
        await npc_queries.create_npc(
            db,
            campaign_id=cid,
            name="Wyn",
            tier="recurring",  # dynamically recruitable, no authored companion_sheet
            class_="rogue",
            level=3,
            max_hp=21,
            hp=21,
            ac=14,
            ability_scores={"str": 10, "dex": 16, "con": 12, "int": 13, "wis": 11, "cha": 14},
            narrative_profile={"name": "Wyn", "personality": "Watchful.", "voice": {}, "goals": {"life": "go home"}},
        )
        await db.commit()

    with patch("cairn.pipelines.turn_graph.recruiter.run", new=_decision("accept", "Fine. I'm in.")):
        await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Wyn"))

    assert await _find_npc(camp["id"], "Wyn") is None
    wyn = next(c for c in await _companions(camp["id"]) if c.name == "Wyn")
    assert wyn.max_hp == 21 and wyn.ac == 14  # derived straight from the NPC row
    assert wyn.class_name == "rogue" and wyn.level == 3
    assert wyn.companion_meta["personal_goal"] == "go home"


async def test_party_full_blocks_recruit(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    for i in range(recruitment.MAX_ACTIVE_COMPANIONS):
        await make_character(
            client,
            camp["id"],
            name=f"Companion {i}",
            is_companion=True,
            narrative_profile={**_COMPANION_PROFILE, "name": f"Companion {i}"},
        )

    with patch("cairn.pipelines.turn_graph.recruiter.run", new=_decision("accept", "I'll come.")):
        out = await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Bram"))

    assert "must step aside" in out["npc_context"]
    assert await _find_npc(camp["id"], "Bram") is not None  # not converted — cap held


async def test_background_npc_not_recruitable_skips_agent(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = uuid.UUID(camp["id"])
    async with db_client.get_session() as db:
        await npc_queries.create_npc(
            db,
            campaign_id=cid,
            name="Pib",
            tier="background",
            narrative_profile={"name": "Pib", "personality": "x", "voice": {}},
        )
        await db.commit()

    with patch("cairn.pipelines.turn_graph.recruiter.run", new=AsyncMock()) as mock_run:
        out = await _resolve_recruitment(_state(camp["id"], "recruit_attempt", "Pib"))

    mock_run.assert_not_awaited()  # a plain background walk-on isn't eligible
    assert "not someone who would throw in" in out["npc_context"]


async def test_dismiss_converts_companion_back_to_npc(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(
        client, camp["id"], name="Kel", is_companion=True, narrative_profile={**_COMPANION_PROFILE, "name": "Kel"}
    )

    out = await _resolve_dismissal(_state(camp["id"], "dismiss_companion", "Kel"))

    assert "parts ways" in out["npc_context"]
    assert await _companions(camp["id"]) == []
    npc = await _find_npc(camp["id"], "Kel")
    assert npc is not None and npc.recruitable and npc.tier == "recurring"
