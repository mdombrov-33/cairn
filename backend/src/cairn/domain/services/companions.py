"""Companion approval subsystem.

Approval is an integer in [-100, 100] living in `Character.companion_meta`. It is
adjusted only by the post-turn `companion_reflector` pass (LLM-judged, in-character).
The raw integer is meta-info — never surfaced to the player; the player sees a vague
`approval_band` and the reasons in the approval log. `mood` is derived here, not stored
by the LLM: the standing sets a baseline, a recent large swing transiently overrides it.
"""

# Player-facing vague standing. The raw number is never shown; this is.
_BANDS: list[tuple[int, str]] = [
    (70, "loyal"),
    (40, "friendly"),
    (15, "warming up"),
    (-14, "neutral"),
    (-39, "cold"),
    (-100, "hostile"),
]


def approval_band(approval: int) -> str:
    """Map raw approval to the vague band the player is allowed to see."""
    for threshold, label in _BANDS:
        if approval >= threshold:
            return label
    return "hostile"


def derive_mood(approval: int, recent_deltas: list[int]) -> str:
    """Deterministic mood: standing sets a baseline, a recent large swing overrides it."""
    if recent_deltas:
        if min(recent_deltas) <= -15:
            return "dejected" if approval <= -20 else "angry"
        if max(recent_deltas) >= 15:
            return "inspired"
    if approval >= 50:
        return "happy"
    if approval <= -40:
        return "dejected"
    if approval <= -15:
        return "upset"
    return "content"
