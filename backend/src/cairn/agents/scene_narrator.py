from collections.abc import AsyncIterator

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
                ),
            }
        ],
        agent="scene_narrator",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    ):
        yield chunk
