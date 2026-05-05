import json

import structlog

from cairn.config import get_settings
from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_with_tools
from cairn.llm.router import get_model
from cairn.mcp.tools.combat_tools import COMBAT_TOOLS, fetch_combat_context
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()

_ALLY_TOOLS = COMBAT_TOOLS


async def run(session_id: str) -> str:
    """Resolve one ally turn (companion character or friendly NPC). Returns a resolution summary string."""  # noqa: E501
    combat_state, party = await fetch_combat_context(session_id)

    idx = combat_state.get("turn_index", 0)
    combatants = combat_state.get("combatants", [])
    if not combatants:
        raise AgentError("ally_ai called with no combatants in combat state")
    current = combatants[idx]

    settings = get_settings()
    version = resolve_version("ally_ai", settings.llm_prompt_versions)
    prompt = load_prompt("ally_ai", version)
    model, fallbacks = get_model("ally_ai", settings.llm_env)

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
            tools=_ALLY_TOOLS,
            agent="ally_ai",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except Exception as exc:
        log.error("ally_ai_failed", error=str(exc))
        raise AgentError(f"AllyAI failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("ally_ai_non_json_response", raw=final_text[:200])
        return final_text
