from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LLMMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMMessageRole
    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("LLM message content must not be empty")


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...] | list[LLMMessage]
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 512
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("LLM request requires at least one message")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage | None = None
    finish_reason: str | None = None


class LLMProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
