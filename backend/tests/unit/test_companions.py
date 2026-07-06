"""Pure-logic tests for the companion approval subsystem (bands + derived mood)."""

from cairn.domain.services.companions import approval_band, derive_mood


class TestApprovalBand:
    def test_bands_across_the_range(self):
        assert approval_band(100) == "loyal"
        assert approval_band(70) == "loyal"
        assert approval_band(69) == "friendly"
        assert approval_band(40) == "friendly"
        assert approval_band(39) == "warming up"
        assert approval_band(15) == "warming up"
        assert approval_band(14) == "neutral"
        assert approval_band(0) == "neutral"
        assert approval_band(-14) == "neutral"
        assert approval_band(-15) == "cold"
        assert approval_band(-39) == "cold"
        assert approval_band(-40) == "hostile"
        assert approval_band(-100) == "hostile"


class TestDeriveMood:
    def test_baseline_bands_with_no_recent_swing(self):
        assert derive_mood(0, []) == "content"
        assert derive_mood(30, []) == "content"
        assert derive_mood(50, []) == "happy"
        assert derive_mood(-15, []) == "upset"
        assert derive_mood(-40, []) == "dejected"

    def test_large_negative_swing_overrides_baseline(self):
        # A recent hard hit reads as anger while standing is still non-terrible...
        assert derive_mood(60, [-16]) == "angry"
        assert derive_mood(10, [-20]) == "angry"
        # ...but as dejection once standing is already low.
        assert derive_mood(-30, [-25]) == "dejected"

    def test_large_positive_swing_reads_as_inspired(self):
        assert derive_mood(20, [18]) == "inspired"
        assert derive_mood(-10, [30]) == "inspired"

    def test_small_swings_do_not_override(self):
        assert derive_mood(0, [5, -5]) == "content"
        assert derive_mood(55, [3]) == "happy"
