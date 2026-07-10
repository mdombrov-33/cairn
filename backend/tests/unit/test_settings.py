from pydantic import ValidationError

from cairn.domain.services.settings import resolve_settings, validate_overrides
from cairn.llm.router import get_model


def test_narrative_preset_resolves_campaign_gameplay_defaults() -> None:
    settings = resolve_settings({})

    assert settings.preset == "narrative"
    assert settings.companion.combat == "ai"
    assert settings.checks.passive_perception == "silent"
    assert settings.death_mode == "narrative"


def test_sparse_override_keeps_its_preset() -> None:
    settings = resolve_settings({"preset": "balanced", "overrides": {"companion": {"combat": "player"}}})

    assert settings.preset == "balanced"
    assert settings.companion.combat == "player"
    assert settings.companion.dialogue == "ai"
    assert settings.checks.passive_insight == "surfaced"


def test_resolved_settings_are_immutable_and_keep_json_shape() -> None:
    settings = resolve_settings({"overrides": {"content": {"lines": ["No spiders"]}}})

    assert settings.as_json()["content"]["lines"] == ["No spiders"]
    try:
        settings.death_mode = "hardcore"  # type: ignore[misc]
    except ValidationError:
        pass
    else:
        raise AssertionError("resolved settings are mutable")


def test_overrides_reject_null_and_unknown_values() -> None:
    for overrides in ({"content": {"lines": None}}, {"companion": {"combat": "invalid"}}):
        try:
            validate_overrides(overrides)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid settings override was accepted")


def test_campaign_settings_reject_model_fields() -> None:
    try:
        validate_overrides({"llm": {"tier": "pro"}})
    except ValueError as exc:
        assert "unknown settings override" in str(exc)
    else:
        raise AssertionError("campaign settings accepted an account-owned model field")


def test_plus_account_tier_uses_task_tuned_bundle() -> None:
    narrator, _ = get_model("scene_narrator", "frontier", "plus")
    router, _ = get_model("intent_router", "frontier", "plus")

    assert narrator == "openai/gpt-5.6-terra"
    assert router == "openai/gpt-5.6-luna"


def test_development_profile_stays_local_even_with_pro_override() -> None:
    model, fallbacks = get_model("scene_narrator", "local", "pro")

    assert model == "ollama/qwen2.5:latest"
    assert fallbacks == []


def test_hosted_tiers_have_explicit_fallbacks() -> None:
    free_model, free_fallbacks = get_model("combat_resolver", "frontier", "free")
    pro_model, pro_fallbacks = get_model("scene_narrator", "frontier", "pro")

    assert (free_model, free_fallbacks) == ("openai/gpt-5.6-luna", ["openai/gpt-5.6-terra"])
    assert (pro_model, pro_fallbacks) == ("openai/gpt-5.6-sol", ["openai/gpt-5.6-terra"])
