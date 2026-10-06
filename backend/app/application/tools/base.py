import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from app.application.tools.errors import ToolExecutionError
from app.domain.ports.tool import (
    RESERVED_ARGUMENT_NAMES,
    Tool,
    ToolContext,
    ToolDefinition,
    ToolInput,
    ToolOutput,
    ToolResult,
)
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT", bound=ToolInput)
OutputT = TypeVar("OutputT", bound=ToolOutput)


class UseCaseTool(Tool, Generic[InputT, OutputT], ABC):
    """Adapter template: validate arguments, call one use case, map errors.

    Tools never talk to the LLM, never touch persistence directly and never
    decide what the agent does next.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        skill_name: str,
        input_model: type[InputT],
        input_schema: dict[str, Any],
        risk_level: RiskLevel = RiskLevel.LOW,
        read_only: bool = False,
        side_effect: bool = False,
        requires_confirmation: bool = False,
        category: str | None = None,
        version: str = "1.0.0",
        error_codes: dict[type[Exception], ToolErrorCode | str] | None = None,
    ) -> None:
        self._definition = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            skill_name=skill_name,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            read_only=read_only,
            side_effect=side_effect,
            category=category,
            version=version,
        )
        self.input_model = input_model
        self.error_codes: dict[type[Exception], ToolErrorCode | str] = error_codes or {}

    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        payload = arguments if isinstance(arguments, dict) else {}
        forbidden = sorted(RESERVED_ARGUMENT_NAMES.intersection(payload))
        if forbidden:
            return self._failure(
                ToolErrorCode.FORBIDDEN_ARGUMENTS,
                "arguments not allowed: " + ", ".join(forbidden),
            )
        try:
            validated = self.input_model.model_validate(payload)
        except ValidationError as error:
            return self._failure(ToolErrorCode.INVALID_ARGUMENTS, _describe(error))
        try:
            output = await self.run(validated, context)
        except ToolExecutionError as error:
            return self._failure(error.code, error.message)
        except Exception as error:
            code = self._code_for(error)
            if code is None:
                logger.exception("tool %s failed unexpectedly", self._definition.name)
                return self._failure(ToolErrorCode.TOOL_EXECUTION_FAILED, "tool execution failed")
            return self._failure(code, str(error) or self._definition.name)
        return ToolResult(
            success=True,
            tool_name=self._definition.name,
            data=_dump(output),
            metadata={"skill": self._definition.skill_name, "action": self._definition.action},
        )

    @abstractmethod
    async def run(self, payload: InputT, context: ToolContext) -> OutputT:
        raise NotImplementedError

    def _code_for(self, error: Exception) -> ToolErrorCode | str | None:
        for error_type in type(error).__mro__:
            if error_type in self.error_codes:
                return self.error_codes[error_type]
        return None

    def _failure(self, code: ToolErrorCode | str, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool_name=self._definition.name,
            error_code=str(code),
            error_message=message,
            metadata={"skill": self._definition.skill_name, "action": self._definition.action},
        )


def _describe(error: ValidationError) -> str:
    parts = []
    for item in error.errors()[:3]:
        location = ".".join(str(piece) for piece in item.get("loc", ()) if piece != "__root__")
        parts.append(f"{location or 'arguments'}: {item.get('msg', 'invalid value')}")
    return "; ".join(parts) or "invalid arguments"


def _dump(output: ToolOutput) -> dict[str, Any]:
    return output.model_dump(mode="json")
