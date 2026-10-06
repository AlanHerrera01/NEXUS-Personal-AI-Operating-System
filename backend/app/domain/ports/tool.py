from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainValidator

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.execution_authorization import ExecutionAuthorization
from app.domain.value_objects.risk_level import RiskLevel

TOOL_NAME_SEPARATOR = "."


def _entity_id_argument(value: Any) -> EntityId:
    if isinstance(value, EntityId):
        return value
    if not isinstance(value, str):
        raise ValueError("identifier must be a string")
    try:
        return EntityId.from_string(value)
    except ValueError as error:
        raise ValueError("identifier must be a UUID") from error


#: Tool arguments that reference an entity: parsed and validated before any use case runs.
EntityIdArgument = Annotated[EntityId, PlainValidator(_entity_id_argument)]

#: Arguments the model must never control: identity, permissions and routing.
RESERVED_ARGUMENT_NAMES = frozenset(
    {
        "user_id",
        "agent_id",
        "agent_run_id",
        "correlation_id",
        "permissions",
        "skill",
        "skill_name",
        "context",
    }
)


@dataclass(frozen=True)
class ToolDefinition:
    """Describes one concrete action. Purely descriptive: no execution logic."""

    name: str
    description: str
    input_schema: dict[str, Any]
    skill_name: str
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    read_only: bool = False
    side_effect: bool = False
    category: str | None = None
    version: str = "1.0.0"
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = None

    def __post_init__(self) -> None:
        if TOOL_NAME_SEPARATOR not in self.name:
            raise ValueError(f"tool name must be namespaced as skill.action: {self.name}")
        if self.read_only and self.side_effect:
            raise ValueError(f"read-only tools cannot declare side effects: {self.name}")
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})

    @property
    def action(self) -> str:
        return self.name.partition(TOOL_NAME_SEPARATOR)[2] or self.name


@dataclass(frozen=True)
class ToolContext:
    """System-controlled execution context. Never sourced from LLM arguments."""

    agent_id: EntityId
    agent_run_id: EntityId
    user_id: EntityId | None = None
    user_request: str = ""
    permissions: frozenset[str] = frozenset()
    correlation_id: str | None = None
    skill_names: frozenset[str] = frozenset()
    #: Proof that the Trust Engine allowed this exact call. Minted by the
    #: orchestrator from a ``PermissionDecision.ALLOW`` and consumed by the
    #: runtime executor. Optional so in-process tools keep working; a sandboxed
    #: tool refuses to run without it.
    authorization: ExecutionAuthorization | None = None


@dataclass(frozen=True)
class ToolResult:
    success: bool
    tool_name: str
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolInput(BaseModel):
    """Base DTO for tool arguments: unknown or reserved fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ToolOutput(BaseModel):
    """Base DTO for tool results returned to the agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Tool(ABC):
    @abstractmethod
    def definition(self) -> ToolDefinition:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError
