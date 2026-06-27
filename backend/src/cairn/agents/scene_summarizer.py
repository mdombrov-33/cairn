"""Scene Summarizer — writes a scene's closing summary when it transitions out.

Called synchronously from the `scene_create` graph node (transitions are rare, so the
latency cost is acceptable). Returns plain prose written to `Scene.summary`.
"""

import structlog

from cairn.llm.client import complete
from cairn.llm.router import agent_setup

log = structlog.get_logger()


async def run(location_name: str, authored_summary: str, turns: list[dict[str, str]]) -> str:
    """Summarize a closing scene from its authored data + the turns that played out in it.

    `turns` is a list of {"player_input", "dm_response"} dicts in order.
    """
    prompt, model, fallbacks = agent_setup("scene_summarizer")

    transcript = "\n\n".join(f"Player: {t['player_input']}\nDM: {t['dm_response']}" for t in turns)
    summary = await complete(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    location_name=location_name,
                    authored_summary=authored_summary,
                    transcript=transcript,
                ),
            }
        ],
        agent="scene_summarizer",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
    return summary.strip()
