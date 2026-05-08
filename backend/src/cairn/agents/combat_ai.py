import json
from typing import Literal

import structlog

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_with_tools
from cairn.llm.router import agent_setup
from cairn.tools import COMBAT_TOOLS, fetch_combat_context

log = structlog.get_logger()


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
