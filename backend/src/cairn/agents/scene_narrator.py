from collections.abc import AsyncIterator

from cairn.config import get_settings
from cairn.llm.client import stream
from cairn.llm.router import get_model
from cairn.prompts.registry import load_prompt, resolve_version


async def run(player_input: str, context: str = "") -> AsyncIterator[str]:
    settings = get_settings()
    version = resolve_version("scene_narrator", settings.llm_prompt_versions)
    prompt = load_prompt("scene_narrator", version)
    model, fallbacks = get_model("scene_narrator", settings.llm_env)

    async for chunk in stream(
        model=model,
        messages=[
            {"role": "user", "content": prompt.render(player_input=player_input, context=context)}
        ],  # noqa: E501
        agent="scene_narrator",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    ):
        yield chunk
