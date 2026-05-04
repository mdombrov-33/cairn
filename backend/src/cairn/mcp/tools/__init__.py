from cairn.mcp.tools.combat import (
    advance_turn,
    apply_condition,
    apply_damage,
    apply_healing,
    end_combat,
    remove_condition,
    roll_death_save,
    start_combat,
)
from cairn.mcp.tools.dice import roll_ability_scores, roll_d20, roll_damage
from cairn.mcp.tools.game_state import get_character, get_combat_state, get_npc, get_party
from cairn.mcp.tools.srd import (
    list_spells_for_class,
    lookup_class,
    lookup_condition,
    lookup_monster,
    lookup_race,
    lookup_spell,
    lookup_weapon,
)

ALL_TOOLS = [
    # Dice
    roll_d20,
    roll_damage,
    roll_ability_scores,
    # SRD lookups
    lookup_spell,
    lookup_monster,
    lookup_condition,
    lookup_weapon,
    lookup_race,
    lookup_class,
    list_spells_for_class,
    # Game state reads
    get_character,
    get_npc,
    get_party,
    get_combat_state,
    # Combat mutations
    start_combat,
    end_combat,
    apply_damage,
    apply_healing,
    apply_condition,
    remove_condition,
    roll_death_save,
    advance_turn,
]

__all__ = ["ALL_TOOLS"]
