from langchain_core.tools import BaseTool

from cairn.tools.combat import (
    advance_turn,
    apply_condition,
    apply_damage,
    apply_effect,
    apply_healing,
    end_combat,
    remove_condition,
    remove_effect,
    roll_death_save,
    start_combat,
)
from cairn.tools.dice import roll_ability_scores, roll_d20, roll_damage
from cairn.tools.game_state import (
    fetch_combat_context,
    get_character,
    get_combat_state,
    get_npc,
    get_party,
)
from cairn.tools.resources import (
    consume_spell_slot,
    drop_concentration,
    restore_resource,
    restore_spell_slot,
    roll_concentration_check,
    set_concentration,
    spend_movement,
    use_action,
    use_bonus_action,
    use_reaction,
    use_resource,
)
from cairn.tools.srd import (
    list_spells_for_class,
    lookup_class,
    lookup_condition,
    lookup_feature,
    lookup_monster,
    lookup_race,
    lookup_spell,
    lookup_subclass,
    lookup_trait,
    lookup_weapon,
)

ALL_TOOLS: list[BaseTool] = [
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
    lookup_feature,
    lookup_trait,
    lookup_subclass,
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
    apply_effect,
    remove_effect,
    # Resource & economy
    consume_spell_slot,
    restore_spell_slot,
    use_resource,
    restore_resource,
    set_concentration,
    drop_concentration,
    roll_concentration_check,
    use_action,
    use_bonus_action,
    use_reaction,
    spend_movement,
]

# Subset for combat agents — excludes state reads injected into prompts directly
COMBAT_TOOLS: list[BaseTool] = [
    roll_d20,
    roll_damage,
    lookup_spell,
    lookup_weapon,
    lookup_monster,
    lookup_condition,
    lookup_feature,
    get_npc,
    apply_damage,
    apply_healing,
    apply_condition,
    remove_condition,
    roll_death_save,
    advance_turn,
    end_combat,
    apply_effect,
    remove_effect,
    consume_spell_slot,
    restore_spell_slot,
    use_resource,
    restore_resource,
    set_concentration,
    drop_concentration,
    roll_concentration_check,
    use_action,
    use_bonus_action,
    use_reaction,
    spend_movement,
]

__all__ = ["ALL_TOOLS", "COMBAT_TOOLS", "fetch_combat_context"]
