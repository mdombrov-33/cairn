"""Foreground turn-runtime interface used by the HTTP turn routes.

This is deliberately the only caller-facing seam for preparing, continuing,
and resuming turns.  Lower-level turn workflow helpers remain implementation
details while the runtime keeps route-level ordering constraints together.
"""

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.application import inspiration as inspiration_service
from cairn.application.turns import service
from cairn.application.turns.types import CompanionActionSuspension, SkillCheckSuspension, TurnSuspension
from cairn.db.models.character import Character
from cairn.db.models.turn import Turn
from cairn.domain.exceptions import ValidationError
from cairn.pipelines.turn_graph import TurnState


@dataclass(frozen=True)
class PreparedTurn:
    turn: Turn
    state: TurnState
    namespace: str


@dataclass(frozen=True)
class CheckResumption:
    turn: Turn
    suspension: SkillCheckSuspension
    active: Character | None
    effective_roll: int
    advantage: bool
    raw_roll: int
    inspiration_roll: int | None
    session_id: uuid.UUID
    campaign_id: uuid.UUID
    namespace: str


@dataclass(frozen=True)
class CompanionActionResumption:
    turn: Turn
    suspension: CompanionActionSuspension
    session_id: uuid.UUID
    namespace: str
    decision: str
    override: str | None


@dataclass(frozen=True)
class ReactionResumption:
    outcome: Any
    turn: Turn
    session_id: uuid.UUID
    campaign_id: uuid.UUID
    namespace: str
    player_input: str


class TurnRuntime:
    """Prepare, continue, and resume a foreground player turn."""

    async def prepare(
        self, db: AsyncSession, *, session_id: uuid.UUID, owner_id: str, player_input: str
    ) -> PreparedTurn:
        turn, state, namespace = await service.prepare(
            db, session_id=session_id, owner_id=owner_id, player_input=player_input
        )
        return PreparedTurn(turn=turn, state=state, namespace=namespace)

    async def prepare_check_resumption(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        owner_id: str,
        roll: int,
        use_inspiration: bool,
        inspiration_roll: int | None,
    ) -> CheckResumption:
        turn, check = await service.prepare_resolve(db, session_id=session_id, turn_id=turn_id, owner_id=owner_id)
        campaign_id, namespace = await service.get_campaign_info(db, session_id=session_id)
        active = await service.get_active_character(db, session_id=session_id)

        effective_roll = roll
        advantage = False
        if use_inspiration:
            if active is None or not active.has_inspiration:
                raise ValidationError("character has no inspiration to spend", code="no_inspiration")
            await inspiration_service.spend(db, character_id=active.id)
            effective_roll = max(roll, inspiration_roll or roll)
            advantage = True

        return CheckResumption(
            turn=turn,
            suspension=SkillCheckSuspension(kind="skill_check", check=check),
            active=active,
            effective_roll=effective_roll,
            advantage=advantage,
            raw_roll=roll,
            inspiration_roll=inspiration_roll,
            session_id=session_id,
            campaign_id=campaign_id,
            namespace=namespace,
        )

    async def prepare_companion_action_resumption(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        owner_id: str,
        decision: str,
        override: str | None,
    ) -> CompanionActionResumption:
        turn, proposal, namespace = await service.prepare_companion_action(
            db, session_id=session_id, turn_id=turn_id, owner_id=owner_id
        )
        return CompanionActionResumption(
            turn=turn,
            suspension=CompanionActionSuspension(kind="companion_action", proposal=proposal),
            session_id=session_id,
            namespace=namespace,
            decision=decision,
            override=override,
        )

    def continue_turn(self, db: AsyncSession, prepared: PreparedTurn) -> AsyncGenerator[dict[str, Any]]:
        return service.stream(db, turn=prepared.turn, state=prepared.state, namespace=prepared.namespace)

    def resume_check(self, db: AsyncSession, resumption: CheckResumption) -> AsyncGenerator[dict[str, Any]]:
        return service.stream_resolve(
            db,
            turn=resumption.turn,
            check=resumption.suspension.check,
            active=resumption.active,
            effective_roll=resumption.effective_roll,
            advantage=resumption.advantage,
            raw_roll=resumption.raw_roll,
            inspiration_roll=resumption.inspiration_roll,
            session_id=resumption.session_id,
            campaign_id=resumption.campaign_id,
            namespace=resumption.namespace,
        )

    def resume_companion_action(
        self, db: AsyncSession, resumption: CompanionActionResumption
    ) -> AsyncGenerator[dict[str, Any]]:
        return service.stream_companion_action(
            db,
            turn=resumption.turn,
            proposal=resumption.suspension.proposal,
            session_id=resumption.session_id,
            namespace=resumption.namespace,
            decision=resumption.decision,
            override=resumption.override,
        )

    async def prepare_reaction_resumption(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        owner_id: str,
        checkpoint_id: str,
        decision: str,
        chosen_reaction: str | None,
    ) -> ReactionResumption:
        outcome, turn, campaign_id, namespace, player_input = await service.resume_reaction(
            db,
            session_id=session_id,
            owner_id=owner_id,
            checkpoint_id=checkpoint_id,
            decision=decision,
            chosen_reaction=chosen_reaction,
        )
        return ReactionResumption(
            outcome=outcome,
            turn=turn,
            session_id=session_id,
            campaign_id=campaign_id,
            namespace=namespace,
            player_input=player_input,
        )

    def resume_reaction(self, db: AsyncSession, resumption: ReactionResumption) -> AsyncGenerator[dict[str, Any]]:
        return service.stream_reaction(
            db,
            outcome=resumption.outcome,
            turn=resumption.turn,
            session_id=resumption.session_id,
            campaign_id=resumption.campaign_id,
            namespace=resumption.namespace,
            player_input=resumption.player_input,
        )


turn_runtime = TurnRuntime()


def suspension_kind(suspension: TurnSuspension) -> str:
    """Expose the tagged discriminator for runtime-focused tests and callers."""
    return suspension.kind
