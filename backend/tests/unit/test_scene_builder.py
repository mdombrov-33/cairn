"""Scene builder mapping — the parsed scene collapses onto the raw authored-scene shape.

The builder generates a `_Scene`; `_to_raw` maps it to the same dict shape `open_scene` parses from
authored YAML, so scene birth needs no special-casing. NPCs the model named outside the roster are
dropped (the builder places people, it does not invent them), and agendas split into their own map.
"""

from cairn.agents.scene_builder import _HiddenDetail, _NpcInScene, _Scene, _Secret, _to_raw


def _scene() -> _Scene:
    return _Scene(
        scene_mode="social",
        safety_level="risky",
        atmosphere="Smoke and low lamplight.",
        surface_details=["A cold hearth"],
        hidden=[_HiddenDetail(check="investigation", dc=14, reveals="A false floorboard.")],
        secrets=[_Secret(unlocked_by="floorboard_found", content="A cache of coin.")],
        threads_in_air=["No one has spoken in a while."],
        npcs_present=[
            _NpcInScene(npc="Old Grim", doing="wiping a glass", attentive_to=["the door"], agenda="watch the room"),
            _NpcInScene(npc="A Ghost", doing="haunting", agenda="scare people"),  # off-roster → dropped
        ],
    )


def test_to_raw_matches_authored_shape() -> None:
    raw = _to_raw(_scene(), roster_names={"Old Grim"})

    assert raw["scene_mode"] == "social"
    assert raw["safety_level"] == "risky"
    assert raw["atmosphere"].startswith("Smoke")
    assert raw["hidden"] == [{"check": "investigation", "dc": 14, "reveals": "A false floorboard."}]
    assert raw["secrets"] == [{"unlocked_by": "floorboard_found", "content": "A cache of coin."}]


def test_to_raw_drops_off_roster_npcs_and_splits_agendas() -> None:
    raw = _to_raw(_scene(), roster_names={"Old Grim"})

    # The ghost was never on the roster — dropped from presence and agendas both.
    assert [p["npc"] for p in raw["npcs_present"]] == ["Old Grim"]
    assert raw["npc_agendas_in_scene"] == {"Old Grim": "watch the room"}
    grim = raw["npcs_present"][0]
    assert grim["doing"] == "wiping a glass"
    assert grim["attentive_to"] == ["the door"]


def test_to_raw_omits_agenda_when_absent() -> None:
    scene = _Scene(atmosphere="Empty room.", npcs_present=[_NpcInScene(npc="Old Grim", doing="loitering")])
    raw = _to_raw(scene, roster_names={"Old Grim"})
    assert raw["npc_agendas_in_scene"] == {}  # no agenda text → no entry
