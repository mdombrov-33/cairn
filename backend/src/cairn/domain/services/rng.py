import random
from typing import Any


def session_rng(session: Any) -> random.Random:
    """Seeded RNG for a session's dice.

    v1 returns a fresh Random(seed) each call — it does NOT persist runtime state
    across rolls, so this is not a replay mechanism (that's a v2 feature). Its purpose
    is deterministic dice in tests: pass a known rng_seed and a test that builds the
    same Random predicts the sequence.
    """
    return random.Random(int(session.rng_seed))
