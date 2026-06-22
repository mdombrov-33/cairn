import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.db.queries import worlds as world_queries

# How much verbatim recent history to include. Day summaries cover everything older;
# RAG over world lore + world bible (later slice) covers the long tail by relevance.
RECENT_DAYS = 5
RECENT_TURNS = 6


async def build_dm_context(db: AsyncSession, session_id: uuid.UUID) -> str:
    """Assemble the layered DM context for a turn.

    Layers, largest scope to smallest:
      1. World lore — only always-on chunks here; relevance retrieval (RAG) lands later.
      2. Current act premise + core events.
      3. Relevant world bible entries — retrieval lands later; omitted for now.
      4. Recent day summaries (last RECENT_DAYS).
      5. Older day summaries — retrieval lands later; omitted for now.
      6. Current scene state — Scene Director lands next slice; omitted for now.
      7. Recent turns verbatim (last RECENT_TURNS completed).
    """
    session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    template = await template_queries.get(db, campaign.template_id)
    world = await world_queries.get(db, template.world_id)

    sections: list[str] = []

    # Layer 1 — world lore (always-on only for now).
    lore_chunks = await world_queries.list_lore_chunks(db, world.id, always_on_only=True)
    if lore_chunks:
        lore_text = "\n".join(f"- {c.title}: {c.content}" for c in lore_chunks)
        sections.append(
            "## Background lore (reference only)\n"
            "Use this only when the player directly engages with it. Do NOT steer scenes "
            "toward these elements.\n"
            f"{lore_text}"
        )

    # Layer 2 — current act.
    acts = template.acts or []
    if 0 <= campaign.current_act_index < len(acts):
        act = acts[campaign.current_act_index]
        core_events = act.get("core_events") or []
        events_text = "\n".join(f"- {e}" for e in core_events)
        sections.append(
            f"## Current act: {act.get('title', '')}\n"
            f"{act.get('premise', '')}\n" + (f"Core events:\n{events_text}" if events_text else "")
        )

    # Layer 4 — recent day summaries.
    day_summaries = await world_bible_queries.list_day_summaries(db, campaign.id)
    if day_summaries:
        recent = day_summaries[-RECENT_DAYS:]
        days_text = "\n\n".join(f"Day {d.day_index}: {d.content}" for d in recent)
        sections.append(f"## Recent days\n{days_text}")

    # Layer 7 — recent completed turns.
    all_turns = await turn_queries.list_turns(db, session_id)
    completed = [t for t in all_turns if t.dm_response]
    if completed:
        recent_turns = completed[-RECENT_TURNS:]
        turns_text = "\n\n".join(f"Player: {t.player_input}\nDM: {t.dm_response}" for t in recent_turns)
        sections.append(f"## Recent turns\n{turns_text}")

    return "\n\n".join(sections)
