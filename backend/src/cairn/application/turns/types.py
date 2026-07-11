"""Turn-owned pause data and runtime outcomes.

The JSONB shapes remain the legacy wire/storage contract.  The tagged runtime
outcomes below give the foreground runtime a safe internal discriminator
without adding fields to persisted ``Turn.check_data``.
"""

from dataclasses import dataclass
from typing import Literal, NotRequired, Required, TypedDict

from cairn.domain.services.settings import ResolvedCampaignSettings


class HelperRef(TypedDict):
    character_id: str
    name: str


class LootIntent(TypedDict):
    npc_id: str
    item_name: str


class CheckData(TypedDict):
    skill: Required[str]
    dc: Required[int]
    modifier: Required[int]
    roll_type: Required[Literal["d20", "advantage", "disadvantage"]]
    status: Required[Literal["pending", "resolved"]]
    helper: NotRequired[HelperRef]
    setup_prose: NotRequired[str]
    roll: NotRequired[int]
    total: NotRequired[int]
    success: NotRequired[bool]
    loot_intent: NotRequired[LootIntent]
    settings: NotRequired[ResolvedCampaignSettings]


class CompanionActionProposal(TypedDict):
    """A paused companion turn replayed through CombatResolver on confirmation."""

    kind: Required[Literal["companion_action"]]
    status: Required[Literal["pending", "resolved"]]
    combatant_id: Required[str]
    combatant_name: Required[str]
    action: Required[str]
    narration: Required[str]
    prior_context: Required[str]
    settings: Required[ResolvedCampaignSettings]


PendingTurnData = CheckData | CompanionActionProposal


@dataclass(frozen=True)
class SkillCheckSuspension:
    kind: Literal["skill_check"]
    check: CheckData


@dataclass(frozen=True)
class CompanionActionSuspension:
    kind: Literal["companion_action"]
    proposal: CompanionActionProposal


type TurnSuspension = SkillCheckSuspension | CompanionActionSuspension
