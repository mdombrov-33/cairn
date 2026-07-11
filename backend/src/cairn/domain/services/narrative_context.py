import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.application import campaign_context
from cairn.db.models.scene import Scene
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.db.queries import worlds as world_queries
from cairn.domain.exceptions import NotFoundError
from cairn.domain.services import campaign_view
from cairn.domain.services import companions as companion_service
from cairn.domain.services.narrative_profile import format_profile

# How much verbatim recent history to include. Day summaries cover everything older;
# RAG over world lore + world bible (later slice) covers the long tail by relevance.
RECENT_DAYS = 5
RECENT_TURNS = 6

# Mid-scene compression: once a scene runs past this many beats, its older turns collapse into
# `scene_progress_summary` and only the last RECENT_TURNS ride along verbatim, so the prompt stays
# bounded however long the scene runs. The summarizer regenerates the summary every N beats.
COMPRESSION_BEAT_THRESHOLD = 8
SUMMARY_REGEN_EVERY = 4

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


def _scene_situation_section(scene: Scene | None) -> str | None:
    """Layer 5 — the current scene as a layered situation, assembled leak-proof.

    Authored content is split into three buckets before it ever reaches the narrator:
      - Known (atmosphere, surface_details, discovered_facts, unlocked secrets, threads) — full text.
      - Hidden — a *stub only* (which check could surface it), never the reveal text.
      - Secrets — omitted entirely until their unlock condition is in discovered_facts.
    The narrator cannot leak what it was never handed. Check-gated reveals reach the known bucket
    only after the skill-check resolver copies them into discovered_facts (next phase).
    """
    if scene is None:
        return None
    authored = scene.authored or {}
    discovered = list(scene.discovered_facts or [])
    parts: list[str] = []

    if atmosphere := authored.get("atmosphere"):
        parts.append(atmosphere.strip())

    surface = authored.get("surface_details") or []
    if surface:
        parts.append("Plainly visible on entry:\n" + "\n".join(f"- {d}" for d in surface))

    # Secrets fold into the known bucket only once every unlock key is a discovered fact.
    unlocked: list[str] = []
    for secret in authored.get("secrets") or []:
        keys = secret.get("unlocked_by")
        needed = [keys] if isinstance(keys, str) else list(keys or [])
        if needed and all(k in discovered for k in needed):
            unlocked.append(secret["content"])

    known = discovered + unlocked
    if known:
        parts.append("Already discovered or perceived here (safe to reference):\n" + "\n".join(f"- {f}" for f in known))

    threads = authored.get("threads_in_air") or []
    if threads:
        parts.append("Unspoken tension in the air:\n" + "\n".join(f"- {t}" for t in threads))

    # Hidden details: stubs only, and only while undiscovered — never the reveal text.
    stubs = sorted(
        {h["check"].capitalize() for h in authored.get("hidden") or [] if h.get("reveals") not in discovered}
    )
    if stubs:
        parts.append(
            f"Undiscovered here: a deliberate check could surface hidden detail(s) ({', '.join(stubs)}). "
            "You may foreshadow that something rewards a closer look, but you do NOT know what it is — "
            "never invent or state it. It reaches you only once the party earns it."
        )

    if not parts:
        return None
    return (
        "## The scene\n"
        "Reveal in layers: narrate atmosphere and what's visible, and surface specific details only "
        "when the player probes them. Treat the discovered list as the party's single source of truth "
        "for what is known.\n\n" + "\n\n".join(parts)
    )


async def _present_cast_section(db: AsyncSession, session_id: uuid.UUID, scene: Scene | None) -> str | None:
    """Layer 6 — the companions and NPCs sharing the current scene.

    The narrator voices NPCs from these profiles and lets companions react. Surface profile only:
    private_facts stay with the dialogue agent (which judges disclosure). Companions carry their
    standing band + mood so the narrator can color a reaction; the raw approval integer never leaves
    the server. NPCs come from the scene's earned `npcs_present` (not the live location roster), each
    carrying its in-the-moment state — what it's doing, watching, and its agenda this scene.
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

    for entry in (scene.npcs_present if scene else []) or []:
        try:
            npc = await npc_queries.get_npc(db, uuid.UUID(entry["npc_id"]))
        except NotFoundError:
            continue  # presence referencing a removed NPC — skip rather than crash the hot path
        header = f"### {npc.name} — NPC (disposition: {npc.disposition})"
        situ: list[str] = []
        if doing := entry.get("doing"):
            situ.append(f"Right now: {doing}")
        if attentive_to := entry.get("attentive_to"):
            situ.append("Watching: " + ", ".join(attentive_to))
        if agenda := entry.get("agenda"):
            situ.append(f"Agenda this scene: {agenda}")
        body = format_profile(npc.narrative_profile, include_private=False)
        blocks.append("\n".join(p for p in (header, body, *situ) if p))

    if not blocks:
        return None
    return (
        "## Present cast\n"
        "The people in this scene. Voice the NPCs from their profiles, and let each push its own "
        "agenda. Let a companion react in 1–2 sentences only when the moment touches their standing, "
        "mood, personal goal, or prejudices — sparingly, and never to steer the player's choices.\n\n"
        + "\n\n".join(blocks)
    )


async def build_dm_context(db: AsyncSession, session_id: uuid.UUID) -> str:
    """Assemble the layered DM context for a turn.

    Layers, largest scope to smallest:
      1. World lore — only always-on chunks here; relevance retrieval (RAG) lands later.
      2. Current act premise + core events.
      3. Relevant world bible entries — retrieval lands later; omitted for now.
      4. Recent day summaries (last RECENT_DAYS).
      5. The scene — the current situation, authored content split leak-proof (known/hidden/secret).
      6. Present cast — companions + scene NPCs (profiles + companion standing/mood).
      7. Recent turns verbatim (last RECENT_TURNS completed).
    """
    session = await session_queries.get_session(db, session_id)
    campaign, template, world = await campaign_context.world_chain(db, session.campaign_id)
    scene = await scene_queries.get_current_scene(db, campaign.id)

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

    # Layer 5 — the scene as a layered situation (leak-proof).
    situation = _scene_situation_section(scene)
    if situation:
        sections.append(situation)

    # Layer 6 — present cast (companions + scene NPCs).
    cast = await _present_cast_section(db, session_id, scene)
    if cast:
        sections.append(cast)

    # Layer 7 — recent turns, scene-scoped with mid-scene compression. A short scene rides along
    # verbatim; once it runs long (beat_count past the threshold), the older turns collapse into
    # `scene_progress_summary` and only the last RECENT_TURNS stay verbatim.
    all_turns = await turn_queries.list_turns(db, session_id)
    scene_turns = campaign_view.scene_turn_views(all_turns, scene.id if scene else None)
    if scene_turns:
        compressed = scene is not None and scene.beat_count > COMPRESSION_BEAT_THRESHOLD
        if compressed and scene and scene.scene_progress_summary:
            sections.append(f"## Earlier this scene\n{scene.scene_progress_summary}")
        window = scene_turns[-RECENT_TURNS:] if compressed else scene_turns
        turns_text = "\n\n".join(f"Player: {t['player_input']}\nDM: {t['dm_response']}" for t in window)
        sections.append(f"## Recent turns\n{turns_text}")

    return "\n\n".join(sections)
