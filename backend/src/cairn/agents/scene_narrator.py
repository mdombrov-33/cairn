from collections.abc import AsyncIterator

from cairn.context import current_campaign_settings
from cairn.llm.client import stream
from cairn.llm.router import agent_setup


async def run(
    player_input: str,
    context: str = "",
    *,
    intro_mode: bool = False,
    is_scene_entry: bool = False,
    death_recovery: bool = False,
    pacing_nudge: str | None = None,
) -> AsyncIterator[str]:
    prompt, model, fallbacks = agent_setup("scene_narrator")
    settings = current_campaign_settings.get() or {}
    content = settings.get("content", {})
    verbosity = settings.get("narration", {}).get("verbosity", "normal")
    max_tokens = {"terse": 450, "normal": 800, "lush": 1200}[verbosity]

    async for chunk in stream(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    player_input=player_input,
                    context=context,
                    intro_mode=intro_mode,
                    is_scene_entry=is_scene_entry,
                    death_recovery=death_recovery,
                    pacing_nudge=pacing_nudge,
                    content=content,
                    verbosity=verbosity,
                    passive_checks=settings.get("checks", {}),
                ),
            }
        ],
        agent="scene_narrator",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
        max_tokens=max_tokens,
    ):
        yield chunk
