import random


def roll_die(sides: int) -> int:
    """Roll a single die with the given number of sides."""
    return random.randint(1, sides)


def roll_advantage(sides: int = 20) -> tuple[int, int, int]:
    """Roll 2 dice, return (die1, die2, result) where result = max."""
    d1, d2 = roll_die(sides), roll_die(sides)
    return d1, d2, max(d1, d2)


def roll_disadvantage(sides: int = 20) -> tuple[int, int, int]:
    """Roll 2 dice, return (die1, die2, result) where result = min."""
    d1, d2 = roll_die(sides), roll_die(sides)
    return d1, d2, min(d1, d2)
