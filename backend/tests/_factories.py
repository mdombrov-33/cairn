import json
from typing import Any

from httpx import AsyncClient

DEFAULT_USER = "user_a"

# Minimum payload accepted by CharacterCreate. Override any field with kwargs.
DEFAULT_CHARACTER: dict[str, Any] = {
    "name": "Ser Aldric",
    "race": "human",
    "character_class": "fighter",
    "background": "soldier",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "skill_choices": ["Perception", "Athletics"],
    "alignment": "Lawful Good",
    "bio": "A seasoned warrior.",
    "personality": "Stoic and direct.",
}


async def make_campaign(
    client: AsyncClient,
    *,
    owner: str = DEFAULT_USER,
    name: str = "Test Campaign",
    template_id: str = "tavern_v1",
) -> dict:
    """Create a campaign owned by `owner`. Returns the campaign JSON."""
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": owner},
        json={"name": name, "template_id": template_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def make_character(
    client: AsyncClient,
    campaign_id: str,
    *,
    owner: str = DEFAULT_USER,
    **overrides: Any,
) -> dict:
    """Create a character. Defaults to a level-1 human fighter.
    Pass keyword overrides to change any field (e.g. character_class="ranger",
    is_companion=True, voice_traits={"accent": "soft"}).
    """
    payload = {**DEFAULT_CHARACTER, **overrides}
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/characters",
        headers={"X-User-Id": owner},
        json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def make_session(
    client: AsyncClient,
    campaign_id: str,
    *,
    owner: str = DEFAULT_USER,
) -> dict:
    """Start a new session for a campaign. Returns the session JSON."""
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": owner},
    )
    assert r.status_code == 201, r.text
    return r.json()


def parse_sse(text: str) -> list[dict]:
    """Parse an SSE response body into a list of {type, data} dicts."""
    events: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["type"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif not line and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events
