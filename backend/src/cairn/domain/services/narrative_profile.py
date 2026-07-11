"""Render a NarrativeProfile blob into a prose block for agent prompts.

Pure formatting — the deep prose identity (NPC/companion `narrative_profile`) is
turned into a labeled text block the dialogue / narrator / ally agents roleplay from.
`include_private` gates `private_facts`: dialogue holds them (the LLM judges when to
reveal); the scene narrator gets the surface only.
"""

from cairn.domain.narrative import NarrativeProfile


def format_profile(profile: NarrativeProfile | None, *, include_private: bool = True) -> str:
    if not profile:
        return ""

    out: list[str] = []

    meta = ", ".join(str(profile[k]) for k in ("race", "age", "profession") if profile.get(k))  # type: ignore[literal-required]
    header = profile.get("name", "Unknown")
    out.append(f"{header} ({meta})" if meta else header)

    if profile.get("physical"):
        out.append(f"Appearance: {profile.get('physical')}")
    if profile.get("personality"):
        out.append(f"Personality: {profile['personality']}")

    voice = profile.get("voice") or {}
    vbits = [f"{k}: {voice[k]}" for k in ("accent", "pace", "vocabulary") if voice.get(k)]  # type: ignore[literal-required]
    if voice.get("speech_quirks"):
        vbits.append("quirks: " + "; ".join(voice.get("speech_quirks", [])))
    if vbits:
        out.append("Voice — " + " | ".join(vbits))

    if profile.get("backstory"):
        out.append(f"History: {profile.get('backstory')}")

    goals = profile.get("goals") or {}
    gbits = [f"{k}: {goals[k]}" for k in ("immediate", "midterm", "life") if goals.get(k)]  # type: ignore[literal-required]
    if gbits:
        out.append("Goals — " + " | ".join(gbits))

    if profile.get("prejudices"):
        out.append("Prejudices: " + "; ".join(profile.get("prejudices", [])))

    rels = profile.get("relationships") or []
    if rels:
        rbits = [
            f"{r.get('name', '?')} ({r.get('relation', '?')}, {r.get('status', '?')})"
            + (f": {r.get('notes')}" if r.get("notes") else "")
            for r in rels
        ]
        out.append("Relationships: " + "; ".join(rbits))

    if include_private and profile.get("private_facts"):
        out.append("Private (known, not volunteered): " + "; ".join(profile.get("private_facts", [])))

    return "\n".join(out)
