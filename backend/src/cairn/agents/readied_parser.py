"""Parse one natural-language readied condition into an engine trigger."""

from cairn.application.combat.plan import ReadiedTrigger
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup


async def run(declaration: str, *, combat_context: str) -> ReadiedTrigger:
    prompt, model, fallbacks = agent_setup("readied_parser")
    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(declaration=declaration, combat_context=combat_context),
            }
        ],
        model_cls=ReadiedTrigger,
        agent="readied_parser",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
