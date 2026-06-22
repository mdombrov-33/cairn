"""Seed authored world + campaign-template content into the database.

Usage: uv run python -m cairn.cli.seed <template_key>   (e.g. tavern_v1)

Authored content lives in files under src/cairn/seed/:
  worlds/<world_key>/world.md         frontmatter: key, name, calendar; body: summary
  worlds/<world_key>/lore/*.md        frontmatter: category, key, title, tags, always_on; body: content
  templates/<template_key>/template.md  frontmatter: key, world, title, status,
                                        always_on_lore_keys, acts; body: premise
  templates/<template_key>/premade_characters/*.md  frontmatter: sheet fields; body: bio

NPC/location blueprints stay as YAML and are cloned per-campaign at campaign creation —
they are NOT seeded here.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import frontmatter
import structlog

from cairn.db import client as db_client
from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import worlds as world_queries

log = structlog.get_logger()

_SEED_DIR = Path(__file__).parent.parent / "seed"


def _load(path: Path) -> tuple[dict[str, Any], str]:
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content.strip()


async def _seed_world(db: Any, world_key: str) -> Any:
    world_dir = _SEED_DIR / "worlds" / world_key
    meta, summary = _load(world_dir / "world.md")
    world = await world_queries.upsert(
        db,
        key=meta["key"],
        name=meta["name"],
        summary=summary or None,
        calendar=meta.get("calendar", {}),
    )

    lore_dir = world_dir / "lore"
    count = 0
    if lore_dir.exists():
        for path in sorted(lore_dir.glob("*.md")):
            lmeta, content = _load(path)
            await world_queries.upsert_lore_chunk(
                db,
                world_id=world.id,
                category=lmeta["category"],
                key=lmeta["key"],
                title=lmeta["title"],
                content=content,
                tags=lmeta.get("tags", []),
                always_on=bool(lmeta.get("always_on", False)),
            )
            count += 1
    log.info("seeded_world", key=world_key, lore_chunks=count)
    return world


async def _seed_template(db: Any, template_key: str) -> None:
    template_dir = _SEED_DIR / "templates" / template_key
    meta, premise = _load(template_dir / "template.md")

    world = await _seed_world(db, meta["world"])

    template = await template_queries.upsert(
        db,
        world_id=world.id,
        key=meta["key"],
        title=meta["title"],
        premise=premise,
        acts=meta.get("acts", []),
        always_on_lore_keys=meta.get("always_on_lore_keys", []),
        status=meta.get("status", "draft"),
    )

    premade_dir = template_dir / "premade_characters"
    count = 0
    if premade_dir.exists():
        for path in sorted(premade_dir.glob("*.md")):
            pmeta, bio = _load(path)
            key = pmeta.pop("key")
            sheet = {**pmeta, "bio": bio}
            await template_queries.upsert_premade(db, template_id=template.id, key=key, sheet=sheet)
            count += 1
    log.info("seeded_template", key=template_key, premades=count)


async def run(template_key: str) -> None:
    async with db_client.get_sessionmaker()() as db, db.begin():
        await _seed_template(db, template_key)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m cairn.cli.seed <template_key>", file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    main()
