import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from cairn.application.turns.epilogue import PostTurnEpilogue


async def test_shutdown_cancels_every_tracked_post_turn_task() -> None:
    epilogue = PostTurnEpilogue()
    blocked = asyncio.Event()

    async def wait_forever(*_args: object) -> None:
        await blocked.wait()

    with (
        patch.object(epilogue, "_run_lore_keeper", new=AsyncMock(side_effect=wait_forever)),
        patch.object(epilogue, "_run_scene_director_post", new=AsyncMock(side_effect=wait_forever)),
        patch.object(epilogue, "_run_companion_reflector", new=AsyncMock(side_effect=wait_forever)),
        patch.object(epilogue, "_run_scene_summarizer", new=AsyncMock(side_effect=wait_forever)),
    ):
        epilogue.schedule(
            "Narration",
            session_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            namespace="test",
            turn_id=uuid.uuid4(),
        )
        await asyncio.sleep(0)

        await epilogue.shutdown()

    assert epilogue._tasks == set()
