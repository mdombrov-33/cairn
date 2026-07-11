import pytest

from cairn.domain.combat_range import srd_range_to_category


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Self", "self"),
        ("Touch", "touch"),
        ("5 feet", "touch"),
        ("30 feet", "close"),
        ("60 feet", "far"),
        ("120 feet", "far"),
        ("150 feet", "far"),
        ("unknown", "out_of_range"),
    ],
)
def test_srd_ranges_map_to_tactical_categories(value: str, expected: str) -> None:
    assert srd_range_to_category(value) == expected
