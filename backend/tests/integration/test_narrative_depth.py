"""Integration tests for Phase 6 — narrator/ally profile injection + disposition-change canon.

The LLM agents (dialogue, narrator, ally) are not exercised here; these lock the wiring that
feeds them: the present-cast section in the DM context (companion standing/mood + scene NPC
profiles, raw approval never leaking), and the deterministic world-bible entry written when an
NPC's disposition shifts in dialogue.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.agents.combat_ai import _companion_dispositions
from cairn.agents.dialogue import DialogueResult
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.services import narrative_context
from cairn.pipelines.turn_graph import TurnState, _resolve_dialogue
from tests._factories import make_campaign, make_character, make_session

_COMPANION_PROFILE = {"name": "VESSA", "personality": "Dry, guards her past.", "voice": {}}


def _dialogue_state(session_id: str, campaign_id: str, npc_name: str) -> TurnState:
    return {
        "session_id": session_id,
        "campaign_id": campaign_id,
        "player_input": f"I threaten {npc_name}.",
        "intent": "npc_dialogue",
        "npc_name": npc_name,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": None,
        "is_scene_entry": False,
        "combat_just_started": False,
        "settings": {},
    }


async def test_context_carries_companion_standing_not_raw_approval(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    comp = await make_character(
        client,
        camp["id"],
        name="Vessa",
        is_companion=True,
        narrative_profile={**_COMPANION_PROFILE, "name": "Vessa"},
    )
    async with db_client.get_session() as db:
        character = await character_queries.get_character(db, uuid.UUID(comp["id"]))
        character.companion_meta = {
            "approval": 63,
            "mood": "happy",
            "personal_goal": "find her sister",
            "approval_log": [],
        }
        await db.commit()

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, uuid.UUID(sess["id"]))

    assert "Present cast" in context
    assert "Vessa" in context
    assert "friendly" in context  # approval 63 → band, not the number
    assert "find her sister" in context
    assert "63" not in context  # the raw integer never reaches the prompt


async def test_context_carries_scene_npc_profile(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(camp["id"]))
        assert scene is not None and scene.location_id is not None
        harl = await npc_queries.create_npc(
            db,
            campaign_id=uuid.UUID(camp["id"]),
            name="Harl",
            location_id=scene.location_id,
            narrative_profile={"name": "Harl", "personality": "Keeps a filthy ledger.", "voice": {}},
        )
        # Presence is earned per-scene now, not the live location roster: seed npcs_present.
        await scene_queries.set_npcs_present(
            db, scene.id, [{"npc_id": str(harl.id), "doing": "counting coppers", "agenda": "skim the till"}]
        )
        await db.commit()

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, uuid.UUID(sess["id"]))

    assert "Harl" in context
    assert "filthy ledger" in context
    assert "counting coppers" in context  # in-the-moment presence state reaches the narrator
    assert "skim the till" in context


async def test_dialogue_disposition_change_writes_world_bible(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        await npc_queries.create_npc(
            db,
            campaign_id=uuid.UUID(camp["id"]),
            name="Old Grim",
            disposition="neutral",
            narrative_profile={"name": "Old Grim", "personality": "Gruff barkeep.", "voice": {}},
        )
        await db.commit()

    with patch(
        "cairn.pipelines.turn_graph.dialogue_agent.run",
        new=AsyncMock(return_value=DialogueResult(dialogue="Get out.", disposition_change="hostile")),
    ):
        await _resolve_dialogue(_dialogue_state(sess["id"], camp["id"], "Old Grim"))

    async with db_client.get_session() as db:
        entries = await world_bible_queries.list_by_campaign(db, uuid.UUID(camp["id"]))
        grim = await npc_queries.find_by_name(db, uuid.UUID(camp["id"]), "Old Grim")

    assert grim is not None and grim.disposition == "hostile"
    rel = [e for e in entries if e.type == "RELATIONSHIP" and "Old Grim" in e.key]
    assert rel, "disposition shift should be recorded in the world bible"
    assert "hostile" in rel[0].content and "neutral" in rel[0].content


async def test_dialogue_no_disposition_change_writes_nothing(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        await npc_queries.create_npc(
            db,
            campaign_id=uuid.UUID(camp["id"]),
            name="Old Grim",
            disposition="neutral",
            narrative_profile={"name": "Old Grim", "personality": "Gruff barkeep.", "voice": {}},
        )
        await db.commit()

    with patch(
        "cairn.pipelines.turn_graph.dialogue_agent.run",
        new=AsyncMock(return_value=DialogueResult(dialogue="Aye, what'll it be?", disposition_change=None)),
    ):
        await _resolve_dialogue(_dialogue_state(sess["id"], camp["id"], "Old Grim"))

    async with db_client.get_session() as db:
        entries = await world_bible_queries.list_by_campaign(db, uuid.UUID(camp["id"]))
    assert [e for e in entries if e.type == "RELATIONSHIP"] == []


def test_companion_dispositions_block_excludes_non_companions() -> None:
    party = [
        {"name": "Hero", "is_companion": False, "narrative_profile": {}, "companion_meta": None},
        {
            "name": "Vessa",
            "is_companion": True,
            "narrative_profile": {"name": "Vessa", "personality": "Dry.", "voice": {}},
            "companion_meta": {"approval": -30, "mood": "angry", "personal_goal": "revenge"},
        },
    ]
    block = _companion_dispositions(party)

    assert "Vessa" in block
    assert "cold" in block  # approval -30 → band
    assert "angry" in block
    assert "revenge" in block
    assert "Hero" not in block  # PCs are not companions
    assert "-30" not in block  # raw integer stays server-side
