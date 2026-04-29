class CairnError(Exception):
    code: str = "cairn_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(CairnError):
    code = "not_found"


class ConflictError(CairnError):
    code = "conflict"


class AgentError(CairnError):
    code = "agent_error"


class RAGError(CairnError):
    code = "rag_error"


class LLMError(CairnError):
    code = "llm_error"


class QueueError(CairnError):
    code = "queue_error"
