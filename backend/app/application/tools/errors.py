from app.domain.value_objects.tool_error_code import ToolErrorCode


class ToolExecutionError(Exception):
    """Raised by use cases to produce a structured, LLM-safe tool failure."""

    def __init__(self, code: ToolErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
