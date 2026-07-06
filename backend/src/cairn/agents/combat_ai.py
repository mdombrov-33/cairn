import json
from typing import Literal

import structlog

from cairn.domain.exceptions import AgentError
from cairn.domain.services import companions
from cairn.domain.services.narrative_profile import format_profile
from cairn.llm.client import complete_with_tools
from cairn.llm.router import agent_setup
from cairn.tools import COMBAT_TOOLS, fetch_combat_context

log = structlog.get_logger()


def _companion_dispositions(party: list[dict]) -> str:
    """A clean per-companion block for the ally prompt: how each companion regards the player.

    The party stat blocks carry raw JSON; this surfaces the standing band + mood + goal + profile
    so tactics emerge from who the companion is and how they feel — never a numeric threshold.
    """
    blocks: list[str] = []
    for c in party:
        if not c.get("is_companion"):
            continue
        meta = c.get("companion_meta") or {}
        band = companions.approval_band(meta.get("approval", 0))
        head = f"{c['name']} — standing: {band}, mood: {meta.get('mood', 'content')}"
        goal = meta.get("personal_goal")
        if goal:
            head += f", personal goal: {goal}"
        profile = format_profile(c.get("narrative_profile"), include_private=False)
        blocks.append(f"{head}\n{profile}" if profile else head)
    return "\n\n".join(blocks)


async def run(session_id: str, role: Literal["ally", "enemy"]) -> str:
    """Resolve one AI-controlled combatant turn. Returns a resolution summary string."""
    combat_state, party = await fetch_combat_context(session_id)

    idx = combat_state.get("turn_index", 0)
    combatants = combat_state.get("combatants", [])
    if not combatants:
        raise AgentError(f"{role}_ai called with no combatants in combat state")
    current = combatants[idx]

    agent_name = f"{role}_ai"
    prompt, model, fallbacks = agent_setup(agent_name)

    rendered = prompt.render(
        session_id=session_id,
        combatant_name=current["name"],
        combatant_type=current["type"],
        combatant_id=current["id"],
        combat_state=json.dumps(combat_state, indent=2),
        party=json.dumps(party, indent=2),
        companion_dispositions=_companion_dispositions(party) if role == "ally" else "",
    )

    try:
        final_text, _ = await complete_with_tools(
            model=model,
            messages=[{"role": "user", "content": rendered}],
            tools=COMBAT_TOOLS,
            agent=agent_name,
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except Exception as exc:
        log.error("combat_ai_failed", role=role, error=str(exc))
        raise AgentError(f"{role.capitalize()}AI failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("combat_ai_non_json_response", role=role, raw=final_text[:200])
        return final_text
