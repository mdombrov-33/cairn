import json
from collections.abc import AsyncIterator

import structlog

from cairn.agents import scene_narrator
from cairn.config import get_settings
from cairn.domain.exceptions import AgentError, ToolError
from cairn.llm.client import complete_with_tools
from cairn.llm.router import get_model
from cairn.mcp.tools import ALL_TOOLS
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()


async def run(
    player_input: str,
    session_id: str,
    context: str = "",
) -> AsyncIterator[str]:
    """Resolve a combat action and stream the narrative.

    Phase 1: Tool loop - LLM calls MCP tools to resolve all D&D mechanics
             (attack rolls, damage, saving throws, conditions, HP updates).
             Returns a structured JSON summary of what happened.

    Phase 2: Narration - scene_narrator streams a vivid description
             using the resolution summary as context.
    """
    resolution_summary = await _resolve_mechanics(player_input, session_id, context)

    narrative_context = f"[COMBAT RESOLUTION]\n{resolution_summary}"
    if context:
        narrative_context += f"\n\n{context}"

    async for chunk in scene_narrator.run(player_input, context=narrative_context):
        yield chunk


async def _resolve_mechanics(
    player_input: str,
    session_id: str,
    context: str,
) -> str:
    """Run the tool loop to resolve combat mechanics.

    Returns a plain-English summary of what mechanically happened,
    extracted from the LLM's final JSON response.
    """
    settings = get_settings()
    version = resolve_version("combat_resolver", settings.llm_prompt_versions)
    prompt = load_prompt("combat_resolver", version)
    model, fallbacks = get_model("combat_resolver", settings.llm_env)

    rendered = prompt.render(
        session_id=session_id,
        player_input=player_input,
        context=context,
    )
    messages = [{"role": "user", "content": rendered}]

    try:
        final_text, _ = await complete_with_tools(
            model=model,
            messages=messages,
            tools=ALL_TOOLS,
            agent="combat_resolver",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except ToolError:
        raise
    except Exception as exc:
        log.error("combat_resolver_failed", error=str(exc))
        raise AgentError(f"CombatResolver failed: {exc}") from exc

    # Extract summary from JSON response
    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        # LLM didn't follow JSON format - use raw text as summary
        log.warning("combat_resolver_non_json_response", raw=final_text[:200])
        return final_text
