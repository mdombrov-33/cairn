"""End-to-end wiring: the pre-pass nudge in TurnState reaches the narrator call.

The integration fake short-circuits the graph to a nudge-less state, so here we override it to
emit a pre-output carrying a nudge and capture the kwarg the narrator is actually invoked with.
"""

from collections.abc import AsyncIterator
from unittest.mock import patch

from httpx import AsyncClient

from tests._factories import make_campaign, make_session

_NUDGE = "This scene is stalling — surface a hidden detail."


async def _state_with_nudge(player_input, session_id, campaign_id):
    return {
        "session_id": str(session_id),
        "campaign_id": str(campaign_id),
        "player_input": player_input,
        "intent": "narrative_action",
        "npc_name": None,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": {
            "combat_trigger": None,
            "scene_transition_pull": None,
            "pacing_nudge": _NUDGE,
        },
        "is_scene_entry": False,
        "combat_just_started": False,
    }


async def test_nudge_reaches_narrator(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    captured: dict[str, str | None] = {}

    def _fake_narrator(player_input, context="", **kwargs) -> AsyncIterator[str]:
        captured["pacing_nudge"] = kwargs.get("pacing_nudge")

        async def _gen() -> AsyncIterator[str]:
            yield "The room holds its breath."

        return _gen()

    with (
        patch("cairn.pipelines.turn_graph.run", new=_state_with_nudge),
        patch("cairn.domain.services.turns.scene_narrator.run", new=_fake_narrator),
    ):
        r = await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I wait and watch"},
        )
        assert r.status_code == 201

    assert captured["pacing_nudge"] == _NUDGE
