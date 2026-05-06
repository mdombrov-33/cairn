class CairnError(Exception):
    code: str = "cairn_error"
    http_status: int = 500

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(CairnError):
    code = "not_found"
    http_status = 404


class ConflictError(CairnError):
    code = "conflict"
    http_status = 409


class AuthError(CairnError):
    code = "unauthorized"
    http_status = 401


class AgentError(CairnError):
    code = "agent_error"
    http_status = 502


class ToolError(CairnError):
    code = "tool_error"
    http_status = 502


class LLMError(CairnError):
    code = "llm_error"
    http_status = 502
