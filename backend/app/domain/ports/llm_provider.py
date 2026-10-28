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
    #: ``None`` defers to the provider's configured value. A concrete default
    #: here would silently outrank that configuration for every caller that does
    #: not set one -- which is all of them but the probe route. That is how a
    #: hard-coded 512 outlived the setting meant to replace it and truncated a
    #: reasoning model before it emitted any content.
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("LLM request requires at least one message")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens < 1:
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
