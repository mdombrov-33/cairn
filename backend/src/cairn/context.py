import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Ambient binding for the turn-event back-channel. Combat tools and other emitters run
# several layers deep (and behind fixed LangChain @tool signatures that can't carry a
# turn_id), so they read the active turn from here rather than threading it through.
current_turn_id: ContextVar[uuid.UUID | None] = ContextVar("current_turn_id", default=None)


@contextmanager
def recording_turn(turn_id: uuid.UUID) -> Iterator[None]:
    """The one sanctioned scope for binding the turn-event back-channel.

    Within it, `emitter.emit` attaches events to `turn_id`; outside any such scope an emit
    is dropped (see `emitter.emit`). Replaces scattered `current_turn_id.set/reset` blocks
    so there is a single, named entry point for event recording.
    """
    token = current_turn_id.set(turn_id)
    try:
        yield
    finally:
        current_turn_id.reset(token)
