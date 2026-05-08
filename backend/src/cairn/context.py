import uuid
from contextvars import ContextVar

current_turn_id: ContextVar[uuid.UUID | None] = ContextVar("current_turn_id", default=None)
