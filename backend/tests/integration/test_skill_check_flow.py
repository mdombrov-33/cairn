"""End-to-end tests for the skill check resolution node: real party data
flowing through real context builders, with only the LLM mocked.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.agents.rules_lawyer import CheckDecision, HelperInfo
from cairn.pipelines.turn_graph import TurnState, _resolve_skill_check

FIGHTER: dict = {
    "name": "Ser Aldric",
    "race": "human",
    "character_class": "fighter",
    "background": "soldier",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "skill_choices": ["Perception", "Athletics"],
    "ac": 16,
    "alignment": "Lawful Good",
    "bio": "A seasoned warrior.",
    "personality": "Stoic and direct.",
}

RANGER_COMPANION: dict = {
    "name": "Bria",
    "race": "human",
    "character_class": "ranger",
    "background": "outlander",
    "ability_scores": {"str": 10, "dex": 15, "con": 13, "int": 8, "wis": 14, "cha": 12},
    "skill_choices": ["Athletics", "Stealth", "Survival"],
    "ac": 14,
    "alignment": "Neutral Good",
    "bio": "A traveling ranger.",
    "personality": "Watchful.",
    "is_companion": True,
    "voice_traits": {"accent": "soft", "pace": "measured"},
}


async def _campaign(client: AsyncClient) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "Test", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201
    return r.json()


async def _character(client: AsyncClient, campaign_id: str, payload: dict) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/characters",
        headers={"X-User-Id": "user_a"},
        json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _session(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 201
    return r.json()


def _state(session_id: str, campaign_id: str, player_input: str) -> TurnState:
    return TurnState(
        session_id=session_id,
        campaign_id=campaign_id,
        player_input=player_input,
        intent="skill_check",
        npc_name=None,
        check=None,
        npc_context=None,
    )


async def test_skill_check_fetches_party_and_calls_rules_lawyer(client: AsyncClient) -> None:
    """End-to-end: party is loaded from DB, context is built, agent is called with it."""
    camp = await _campaign(client)
    await _character(client, camp["id"], FIGHTER)
    await _character(client, camp["id"], RANGER_COMPANION)
    sess = await _session(client, camp["id"])

    fake_run = AsyncMock(
        return_value=CheckDecision(
            skill="athletics", dc=14, modifier=4, roll_type="d20", helper=None
        )
    )
    with patch("cairn.pipelines.turn_graph.rules_lawyer.run", fake_run):
        result = await _resolve_skill_check(
            _state(sess["id"], camp["id"], "I try to climb the wall")
        )

    fake_run.assert_called_once()
    kwargs = fake_run.call_args.kwargs
    # The active PC's sheet is injected
    assert "Ser Aldric" in kwargs["character_context"]
    # Athletics is proficient; the exact total depends on racial bonuses applied at creation
    assert "athletics: +" in kwargs["character_context"]
    assert "athletics: +5 (proficient)" in kwargs["character_context"]
    # The party manifest names the companion
    assert "Bria" in kwargs["party_manifest"]
    assert "companion (AI)" in kwargs["party_manifest"]
    # The PC is excluded from the manifest
    assert "Ser Aldric" not in kwargs["party_manifest"]
    # Returned check has no helper
    assert result["check"]["skill"] == "athletics"
    assert "helper" not in result["check"]


async def test_skill_check_with_valid_helper_propagates(client: AsyncClient) -> None:
    camp = await _campaign(client)
    await _character(client, camp["id"], FIGHTER)
    companion = await _character(client, camp["id"], RANGER_COMPANION)
    sess = await _session(client, camp["id"])

    fake_run = AsyncMock(
        return_value=CheckDecision(
            skill="medicine",
            dc=14,
            modifier=2,
            roll_type="advantage",
            helper=HelperInfo(character_id=companion["id"], name="Bria"),
        )
    )
    with patch("cairn.pipelines.turn_graph.rules_lawyer.run", fake_run):
        result = await _resolve_skill_check(
            _state(sess["id"], camp["id"], "I tend to my wound with Bria's help")
        )

    assert result["check"]["helper"]["character_id"] == companion["id"]
    assert result["check"]["helper"]["name"] == "Bria"
    assert result["check"]["roll_type"] == "advantage"


async def test_skill_check_drops_invalid_helper(client: AsyncClient) -> None:
    """Hallucinated helper UUID is filtered out — no helper key in the result."""
    camp = await _campaign(client)
    await _character(client, camp["id"], FIGHTER)
    await _character(client, camp["id"], RANGER_COMPANION)
    sess = await _session(client, camp["id"])

    bogus_id = str(uuid.uuid4())
    fake_run = AsyncMock(
        return_value=CheckDecision(
            skill="athletics",
            dc=14,
            modifier=4,
            roll_type="advantage",
            helper=HelperInfo(character_id=bogus_id, name="Ghost"),
        )
    )
    with patch("cairn.pipelines.turn_graph.rules_lawyer.run", fake_run):
        result = await _resolve_skill_check(_state(sess["id"], camp["id"], "I climb the wall"))

    assert "helper" not in result["check"]
    # roll_type is preserved as-is — we only drop the helper reference
    assert result["check"]["roll_type"] == "advantage"
