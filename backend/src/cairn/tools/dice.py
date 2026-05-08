import math
import random
import re
from typing import Annotated

from langchain_core.tools import tool


def _roll_die(sides: int) -> int:
    return random.randint(1, sides)


def parse_and_roll(expression: str) -> tuple[list[int], int]:
    """Parse '8d6', '1d6+2', '2d8-1' and roll."""
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    rolls = [_roll_die(sides) for _ in range(count)]
    return rolls, sum(rolls) + modifier


@tool
async def roll_d20(
    modifier: Annotated[int, "Integer modifier to add (can be negative)."] = 0,
    roll_type: Annotated[
        str, '"normal", "advantage" (higher of two), or "disadvantage" (lower of two).'
    ] = "normal",
) -> dict:
    """Roll a d20 for attack rolls, saving throws, or ability checks."""
    if roll_type == "advantage":
        r1, r2 = _roll_die(20), _roll_die(20)
        result = max(r1, r2)
        rolls = [r1, r2]
    elif roll_type == "disadvantage":
        r1, r2 = _roll_die(20), _roll_die(20)
        result = min(r1, r2)
        rolls = [r1, r2]
    else:
        result = _roll_die(20)
        rolls = [result]
    return {
        "rolls": rolls,
        "result": result,
        "modifier": modifier,
        "total": result + modifier,
        "natural_20": result == 20,
        "natural_1": result == 1,
    }


@tool
async def roll_damage(
    expression: Annotated[str, 'Dice notation, e.g. "8d6", "1d6+2", "2d8-1", "4d6+4".'],
) -> dict:
    """Roll damage dice using a standard dice expression like "8d6", "1d6+2", "2d8-1"."""
    rolls, total = parse_and_roll(expression)
    return {"expression": expression, "rolls": rolls, "total": max(0, total)}


@tool
async def roll_ability_scores() -> dict:
    """Roll a full set of ability scores for character creation using 4d6-drop-lowest."""
    detail = []
    scores = []
    for _ in range(6):
        rolls = [_roll_die(6) for _ in range(4)]
        kept = sorted(rolls)[1:]
        score = sum(kept)
        scores.append(score)
        detail.append({"rolled": rolls, "kept": kept, "score": score})
    return {
        "scores": sorted(scores, reverse=True),
        "detail": detail,
        "modifiers": {s: math.floor((s - 10) / 2) for s in scores},
    }
