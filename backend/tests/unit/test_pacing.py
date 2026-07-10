"""Deterministic pacing-nudge math — the Scene Director pre-pass's stalling ladder.

The nudge is never an LLM decision: it's pure scene-state math. Stalling is keyed on
turns-since-last-revelation, so an engaged scene that keeps surfacing things is never nudged
however long it runs.
"""

from cairn.agents.scene_director import _NpcUpdate, _post_output, _PostDecision, compute_pacing_nudge


def test_calm_mid_scene_gets_no_nudge() -> None:
    assert (
        compute_pacing_nudge(scene_mode="exploration", beat_count=8, tension_level=2, turns_since_revelation=3) is None
    )


def test_early_exploration_stays_descriptive() -> None:
    nudge = compute_pacing_nudge(scene_mode="exploration", beat_count=2, tension_level=0, turns_since_revelation=2)
    assert nudge is not None and "descriptive" in nudge


def test_early_nudge_is_exploration_only() -> None:
    # A social scene early on gets no "stay descriptive" nudge.
    assert compute_pacing_nudge(scene_mode="social", beat_count=2, tension_level=0, turns_since_revelation=2) is None


def test_long_silent_scene_stalls() -> None:
    # Nothing ever discovered → turns_since equals the beat count → past the stall bar.
    nudge = compute_pacing_nudge(scene_mode="social", beat_count=20, tension_level=0, turns_since_revelation=20)
    assert nudge is not None and "stalling" in nudge


def test_long_but_engaged_scene_does_not_stall() -> None:
    # 20 beats deep but a discovery landed recently → not stalling, no nudge.
    assert compute_pacing_nudge(scene_mode="social", beat_count=20, tension_level=0, turns_since_revelation=2) is None


def test_high_tension_offers_escalation() -> None:
    nudge = compute_pacing_nudge(scene_mode="social", beat_count=10, tension_level=8, turns_since_revelation=3)
    assert nudge is not None and "Escalation" in nudge


def test_tension_takes_priority_over_stall() -> None:
    # Both a stall and an escalation hold — escalation wins.
    nudge = compute_pacing_nudge(scene_mode="social", beat_count=30, tension_level=9, turns_since_revelation=30)
    assert nudge is not None and "Escalation" in nudge


# --- post-pass decision -> output mapping -----------------------------------------


def test_post_output_drops_invalid_mood() -> None:
    out = _post_output(_PostDecision(mood="euphoric", tension_delta=1))
    assert out["mood"] is None  # not one of the four valid moods
    assert out["tension_delta"] == 1  # rest of the decision survives


def test_post_output_keeps_valid_mood() -> None:
    assert _post_output(_PostDecision(mood="charged"))["mood"] == "charged"


def test_post_output_strips_null_npc_update_fields() -> None:
    out = _post_output(_PostDecision(npc_updates=[_NpcUpdate(npc_id="grim", agenda="draw steel")]))
    assert out["npc_updates"] == [{"npc_id": "grim", "agenda": "draw steel"}]  # doing/attentive_to omitted


def test_post_output_discards_time_skip_without_transition() -> None:
    # Time only advances at a scene boundary — a stray hours value with no push is dropped.
    assert _post_output(_PostDecision(time_advance_hours=8))["time_advance_hours"] == 0
