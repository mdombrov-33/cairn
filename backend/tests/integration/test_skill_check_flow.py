import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.agents.rules_lawyer import CheckDecision, HelperInfo
from cairn.pipelines.turn_graph import TurnState, _resolve_skill_check
from tests._factories import make_campaign, make_character, make_session

RANGER_COMPANION: dict = {
    "name": "Bria",
    "race": "human",
    "character_class": "ranger",
    "background": "outlander",
    "ability_scores": {"str": 10, "dex": 15, "con": 13, "int": 8, "wis": 14, "cha": 12},
    "skill_choices": ["Athletics", "Stealth", "Survival"],
    "alignment": "Neutral Good",
    "bio": "A traveling ranger.",
    "personality": "Watchful.",
    "is_companion": True,
    "voice_traits": {"accent": "soft", "pace": "measured"},
}


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
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    await make_character(client, camp["id"], **RANGER_COMPANION)
    sess = await make_session(client, camp["id"])

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
    assert "Ser Aldric" in kwargs["character_context"]
    # Athletics is proficient; the exact total depends on racial bonuses applied at creation
    assert "athletics: +5 (proficient)" in kwargs["character_context"]
    assert "Bria" in kwargs["party_manifest"]
    assert "companion (AI)" in kwargs["party_manifest"]
    assert "Ser Aldric" not in kwargs["party_manifest"]
    assert result["check"]["skill"] == "athletics"
    assert "helper" not in result["check"]


async def test_skill_check_with_valid_helper_propagates(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    companion = await make_character(client, camp["id"], **RANGER_COMPANION)
    sess = await make_session(client, camp["id"])

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
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    await make_character(client, camp["id"], **RANGER_COMPANION)
    sess = await make_session(client, camp["id"])

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
