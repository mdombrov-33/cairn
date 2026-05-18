from collections.abc import AsyncIterator

from cairn.llm.client import stream
from cairn.llm.router import agent_setup


async def run(player_input: str, context: str = "") -> AsyncIterator[str]:
    prompt, model, fallbacks = agent_setup("scene_narrator")

    async for chunk in stream(
        model=model,
        messages=[{"role": "user", "content": prompt.render(player_input=player_input, context=context)}],
        agent="scene_narrator",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    ):
        yield chunk
