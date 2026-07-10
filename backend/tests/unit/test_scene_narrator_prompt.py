"""The narrator prompt threads the pre-pass pacing nudge as soft guidance.

The nudge is deterministic scene-state math (see test_pacing); here we lock that when it is
present it reaches the narrator flagged as ignorable soft guidance, and when absent it leaves no
trace in the rendered prompt.
"""

from cairn.prompts.registry import load_prompt

_NUDGE = "This scene is stalling — surface a hidden detail."


def _render(**kwargs) -> str:
    return load_prompt("scene_narrator", "v1").render(player_input="I wait", context="", **kwargs)


def test_pacing_nudge_is_injected_as_soft_guidance() -> None:
    out = _render(pacing_nudge=_NUDGE)
    assert _NUDGE in out
    assert "soft guidance" in out  # framed as ignorable, not a command


def test_no_pacing_line_when_nudge_absent() -> None:
    assert "Pacing (soft guidance" not in _render(pacing_nudge=None)


def test_scene_running_rules_are_present() -> None:
    # The withholding / don't-play-for-the-player rules ship in the base prompt, nudge or not.
    out = _render(pacing_nudge=None)
    assert "Withhold by default" in out
    assert "Don't play for the player" in out


def test_content_and_verbosity_settings_reach_the_prompt() -> None:
    out = _render(
        pacing_nudge=None,
        verbosity="terse",
        content={"gore": "off", "lines": ["self-harm"], "tone_note": "hopeful"},
        passive_checks={"passive_perception": "surfaced", "passive_insight": "silent"},
    )

    assert "Narration setting: terse" in out
    assert "gore: off" in out
    assert "self-harm" in out
    assert "perception=surfaced" in out
