from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.entities.agent_run import AgentRun


class AgentDecisionType(StrEnum):
    FINAL = "FINAL"
    TOOL_CALL = "TOOL_CALL"
    ASK_USER = "ASK_USER"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AgentDecision:
    decision_type: AgentDecisionType
    response: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    question: str | None = None
    error: str | None = None

    @classmethod
    def final(cls, response: str) -> "AgentDecision":
        return cls(AgentDecisionType.FINAL, response=response)

    @classmethod
    def tool_call(cls, tool_name: str, arguments: dict[str, Any]) -> "AgentDecision":
        return cls(AgentDecisionType.TOOL_CALL, tool_name=tool_name, arguments=arguments)

    @classmethod
    def ask_user(cls, question: str) -> "AgentDecision":
        return cls(AgentDecisionType.ASK_USER, question=question)


class AgentBrain(ABC):
    @abstractmethod
    async def decide(self, agent_run: AgentRun, context: dict[str, Any], tool_definitions: list[Any]) -> AgentDecision:
        raise NotImplementedError
