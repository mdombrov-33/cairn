from unittest.mock import patch

import pytest

from cairn.agents import intent_router


@pytest.mark.asyncio
async def test_parses_skill_check_with_npc_name_null():
    with patch(
        "cairn.agents.intent_router.complete",
        return_value='{"intent": "skill_check", "npc_name": null}',
    ):
        intent, npc_name = await intent_router.run("I want to make an Arcana check")
    assert intent == "skill_check"
    assert npc_name is None


@pytest.mark.asyncio
async def test_parses_narrative_action():
    with patch(
        "cairn.agents.intent_router.complete",
        return_value='{"intent": "narrative_action", "npc_name": null}',
    ):
        intent, npc_name = await intent_router.run("I walk into the tavern")
    assert intent == "narrative_action"
    assert npc_name is None


@pytest.mark.asyncio
async def test_parses_npc_dialogue_with_name():
    with patch(
        "cairn.agents.intent_router.complete",
        return_value='{"intent": "npc_dialogue", "npc_name": "bartender"}',
    ):
        intent, npc_name = await intent_router.run('I ask the bartender "what news?"')
    assert intent == "npc_dialogue"
    assert npc_name == "bartender"


@pytest.mark.asyncio
async def test_strips_markdown_fences():
    with patch(
        "cairn.agents.intent_router.complete",
        return_value='```json\n{"intent": "skill_check", "npc_name": null}\n```',
    ):
        intent, _ = await intent_router.run("anything")
    assert intent == "skill_check"


def test_prompt_includes_hybrid_agency_guidance():
    """The Slice 3 Verify criterion: explicit roll requests are valid skill_check inputs.
    This test pins the prompt content so a future edit can't silently drop the guidance.
    """
    from cairn.llm.router import agent_setup

    prompt, _, _ = agent_setup("intent_router")
    rendered = prompt.render(player_input="test")
    body_lower = rendered.lower()
    assert "hybrid agency" in body_lower
    assert "explicit" in body_lower
    assert "implicit" in body_lower
