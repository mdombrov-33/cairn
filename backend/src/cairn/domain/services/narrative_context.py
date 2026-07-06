import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.db.queries import worlds as world_queries
from cairn.domain.services import campaign_view
from cairn.domain.services import companions as companion_service
from cairn.domain.services.narrative_profile import format_profile

# How much verbatim recent history to include. Day summaries cover everything older;
# RAG over world lore + world bible (later slice) covers the long tail by relevance.
RECENT_DAYS = 5
RECENT_TURNS = 6

# The opening turns of a fresh campaign weave in a custom PC's backstory before normal play.
INTRO_TURNS = 3


async def is_intro_mode(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """Whether the narrator should weave in backstory for the player's own custom character.

    True only for the first INTRO_TURNS turns and only for a custom PC — a pre-made pick already
    has its arc established, so it gets no onboarding.
    """
    turns = await turn_queries.list_turns(db, session_id)
    if len(turns) > INTRO_TURNS:
        return False
    party = await character_queries.get_party_for_session(db, session_id)
    active = next((c for c in party if not c.is_companion), None)
    return active is not None and active.created_from_premade_id is None


async def _present_cast_section(db: AsyncSession, campaign_id: uuid.UUID, session_id: uuid.UUID) -> str | None:
    """Layer 6 (partial) — the companions and NPCs sharing the current scene.

    The narrator voices NPCs from these profiles and lets companions react. Surface profile only:
    private_facts stay with the dialogue agent (which judges disclosure). Companions carry their
    standing band + mood so the narrator can color a reaction; the raw approval integer never leaves
    the server. Scene mode / tension state lands in the next slice.
    """
    blocks: list[str] = []

    party = await character_queries.get_party_for_session(db, session_id)
    for c in (m for m in party if m.is_companion and m.status == "active"):
        meta = c.companion_meta or {}
        band = companion_service.approval_band(meta.get("approval", 0))
        header = f"### {c.name} — companion (standing: {band}, mood: {meta.get('mood', 'content')})"
        goal = meta.get("personal_goal")
        parts = (
            header,
            format_profile(c.narrative_profile, include_private=False),
            f"Personal goal: {goal}" if goal else "",
        )
        blocks.append("\n".join(p for p in parts if p))

    scene = await scene_queries.get_current_scene(db, campaign_id)
    if scene is not None and scene.location_id is not None:
        for n in await npc_queries.list_by_location(db, campaign_id, scene.location_id):
            header = f"### {n.name} — NPC (disposition: {n.disposition})"
            body = format_profile(n.narrative_profile, include_private=False)
            blocks.append(f"{header}\n{body}" if body else header)

    if not blocks:
        return None
    return (
        "## Present cast\n"
        "The people in this scene. Voice the NPCs from their profiles. Let a companion react in "
        "1–2 sentences only when the moment touches their standing, mood, personal goal, or "
        "prejudices — sparingly, and never to steer the player's choices.\n\n" + "\n\n".join(blocks)
    )


async def build_dm_context(db: AsyncSession, session_id: uuid.UUID) -> str:
    """Assemble the layered DM context for a turn.

    Layers, largest scope to smallest:
      1. World lore — only always-on chunks here; relevance retrieval (RAG) lands later.
      2. Current act premise + core events.
      3. Relevant world bible entries — retrieval lands later; omitted for now.
      4. Recent day summaries (last RECENT_DAYS).
      5. Older day summaries — retrieval lands later; omitted for now.
      6. Present cast — companions + scene NPCs (profiles + companion standing/mood).
      7. Recent turns verbatim (last RECENT_TURNS completed).
    """
    session = await session_queries.get_session(db, session_id)
    campaign, template, world = await campaign_view.world_chain(db, session.campaign_id)

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
    act = campaign_view.act_at(template, campaign.current_act_index)
    if act:
        events_text = "\n".join(f"- {e}" for e in act["core_events"])
        sections.append(
            f"## Current act: {act['title']}\n"
            f"{act['premise']}\n" + (f"Core events:\n{events_text}" if events_text else "")
        )

    # Layer 4 — recent day summaries.
    day_summaries = await world_bible_queries.list_day_summaries(db, campaign.id)
    if day_summaries:
        recent = day_summaries[-RECENT_DAYS:]
        days_text = "\n\n".join(f"Day {d.day_index}: {d.content}" for d in recent)
        sections.append(f"## Recent days\n{days_text}")

    # Layer 6 — present cast (companions + scene NPCs).
    cast = await _present_cast_section(db, campaign.id, session_id)
    if cast:
        sections.append(cast)

    # Layer 7 — recent completed turns.
    all_turns = await turn_queries.list_turns(db, session_id)
    completed = [t for t in all_turns if t.dm_response]
    if completed:
        recent_turns = completed[-RECENT_TURNS:]
        turns_text = "\n\n".join(f"Player: {t.player_input}\nDM: {t.dm_response}" for t in recent_turns)
        sections.append(f"## Recent turns\n{turns_text}")

    return "\n\n".join(sections)
