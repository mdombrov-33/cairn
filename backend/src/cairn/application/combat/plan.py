"""Typed intent emitted by combat planners and consumed by the executor."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MoveOperation(_Operation):
    kind: Literal["move"]
    actor_id: str
    target_zone_id: str
    disengage: bool = False


class AttackOperation(_Operation):
    kind: Literal["attack"]
    actor_id: str
    target_id: str
    attack_name: str | None = None


class CastOperation(_Operation):
    kind: Literal["cast"]
    actor_id: str
    spell_name: str
    target_ids: tuple[str, ...]
    slot_level: int = Field(ge=0, le=9)

    @field_validator("target_ids", mode="before")
    @classmethod
    def freeze_targets(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReadiedTrigger(_Operation):
    creature: str
    event: Literal["enters-zone", "casts-spell", "moves-within-reach", "attacks"]
    zone: str | None = None
    target: str | None = None


class ReadyOperation(_Operation):
    kind: Literal["ready"]
    actor_id: str
    trigger: str
    action: AttackOperation | CastOperation
    parsed_trigger: ReadiedTrigger | None = None


class ApplyConditionOperation(_Operation):
    kind: Literal["apply_condition"]
    actor_id: str
    target_id: str
    condition: str


class EndCombatOperation(_Operation):
    kind: Literal["end_combat"]
    actor_id: str
    outcome: Literal["victory", "defeat", "retreat", "resolved"]


class AdvanceTurnOperation(_Operation):
    kind: Literal["advance_turn"]
    actor_id: str


CombatOperation = Annotated[
    MoveOperation
    | AttackOperation
    | CastOperation
    | ReadyOperation
    | ApplyConditionOperation
    | EndCombatOperation
    | AdvanceTurnOperation,
    Field(discriminator="kind"),
]


class CombatPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operations: tuple[CombatOperation, ...]
    summary: str = ""

    @field_validator("operations", mode="before")
    @classmethod
    def freeze_operations(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value
