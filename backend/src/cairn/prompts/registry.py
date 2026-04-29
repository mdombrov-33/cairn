import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import frontmatter
from jinja2 import Template

_PROMPTS_DIR = Path(__file__).parent


@dataclass
class Prompt:
    meta: dict[str, Any]
    template: Template

    @property
    def temperature(self) -> float:
        return float(self.meta.get("temperature", 1.0))

    def render(self, **kwargs: object) -> str:
        return self.template.render(**kwargs)


@lru_cache
def load_prompt(name: str, version: str) -> Prompt:
    """Load and cache a prompt by name and version."""
    path = _PROMPTS_DIR / name / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {name}/{version}")
    post = frontmatter.load(str(path))
    return Prompt(meta=dict(post.metadata), template=Template(post.content))


def resolve_version(name: str, prompt_versions_json: str) -> str:
    """Pick the active version for a prompt from the LLM_PROMPT_VERSIONS env map."""
    return json.loads(prompt_versions_json).get(name, "v1")
