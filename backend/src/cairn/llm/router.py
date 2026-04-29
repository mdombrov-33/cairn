from functools import lru_cache
from pathlib import Path

import yaml

_MODELS_PATH = Path(__file__).parent / "models.yaml"


@lru_cache
def _load_models() -> dict:
    return yaml.safe_load(_MODELS_PATH.read_text())


def get_model(agent: str, llm_env: str) -> tuple[str, list[str]]:
    """Return (primary_model, fallbacks) for a given agent and environment."""
    data = _load_models()
    agents = data.get("agents", {})

    if agent in agents and llm_env in agents[agent]:
        tier = agents[agent][llm_env]
    else:
        tier = data["defaults"][llm_env]

    primary: str = tier["primary"]
    fallbacks: list[str] = [tier["fallback"]] if "fallback" in tier else []
    return primary, fallbacks
