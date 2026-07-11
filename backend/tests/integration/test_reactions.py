import uuid

from httpx import AsyncClient

from cairn.application.combat.executor import ExecutionSuspended, execute_plan, resume_reaction
from cairn.application.combat.plan import AttackOperation, CombatPlan
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError
from cairn.tools.combat import start_combat
from tests._factories import make_campaign, make_character, make_session


async def test_shield_suspends_persists_and_resumes_without_reroll(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    character = await make_character(client, campaign["id"])
    session = await make_session(client, campaign["id"])
    await client.patch(
        f"/v1/campaigns/{campaign['id']}/settings",
        headers={"X-User-Id": "user_a"},
        json={"overrides": {"reaction_control": "suggest"}},
    )
    started = await start_combat.ainvoke(
        {"session_id": session["id"], "enemies_json": '[{"type":"monster","name":"goblin"}]'}
    )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    async with db_client.get_session() as db:
        pc = await character_queries.get_character(db, uuid.UUID(character["id"]))
        pc.spells_known = ["Shield"]
        pc.prepared_spells = ["Shield"]
        pc.spell_slots = {"1": 1}
        db_session = await session_queries.get_session(db, uuid.UUID(session["id"]))
        db_session.rng_seed = 16

    plan = CombatPlan(
        operations=(
            AttackOperation(kind="attack", actor_id=goblin["id"], target_id=character["id"], attack_name="Scimitar"),
        )
    )
    async with db_client.get_session() as db:
        outcome = await execute_plan(db, session_id=uuid.UUID(session["id"]), plan=plan)
    assert isinstance(outcome, ExecutionSuspended)
    checkpoint = outcome.prompt["checkpoint_id"]
    assert outcome.prompt["frame"]["roll"]["natural"] == 12

    async with db_client.get_session() as db:
        completed = await resume_reaction(
            db,
            session_id=uuid.UUID(session["id"]),
            owner_id="user_a",
            checkpoint_id=checkpoint,
            decision="take",
            chosen_reaction="shield",
        )
    assert any("cast Shield" in fact for fact in completed.facts)  # type: ignore[union-attr]

    async with db_client.get_session() as db:
        pc = await character_queries.get_character(db, uuid.UUID(character["id"]))
        persisted = await session_queries.get_session(db, uuid.UUID(session["id"]))
        assert pc.spell_slots == {"1": 0}
        assert pc.hp == character["hp"]
        assert persisted.combat_state is not None
        assert persisted.combat_state["turn_economy"][character["id"]]["reaction_used"] is True
        assert persisted.combat_state.get("pending_reaction") is None

    async with db_client.get_session() as db:
        try:
            await resume_reaction(
                db,
                session_id=uuid.UUID(session["id"]),
                owner_id="user_a",
                checkpoint_id=checkpoint,
                decision="take",
                chosen_reaction="shield",
            )
        except ConflictError as exc:
            assert exc.code == "stale_reaction"
        else:
            raise AssertionError("duplicate reaction checkpoint was accepted")
