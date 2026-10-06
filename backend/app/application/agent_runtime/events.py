"""Structured observability for the runtime layer.

Every record carries the ownership coordinates (user, agent, run, runtime,
tool) and a timestamp. No record may contain a secret: the only credential
field that is ever emitted is the *name* of a credential, never its value.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_event_type import RuntimeEventType, SecurityEventType

logger = logging.getLogger("nexus.runtime")

#: Keys scrubbed from every event payload before it is written.
REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credential_value",
        "env",
        "environment",
        "password",
        "private_key",
        "secret",
        "stdin",
        "token",
        "value",
    }
)

REDACTED = "***redacted***"


def redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop anything credential-shaped. Applied to every emitted record."""
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in REDACTED_KEYS:
            safe[key] = REDACTED
        elif isinstance(value, Mapping):
            safe[key] = redact(value)
        else:
            safe[key] = value
    return safe


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event: str
    timestamp: str
    user_id: str | None = None
    agent_id: str | None = None
    agent_run_id: str | None = None
    runtime_id: str | None = None
    sandbox_id: str | None = None
    tool_id: str | None = None
    provider: str | None = None
    status: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "event": self.event,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "agent_run_id": self.agent_run_id,
            "runtime_id": self.runtime_id,
            "sandbox_id": self.sandbox_id,
            "tool_id": self.tool_id,
            "provider": self.provider,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "detail": self.detail,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        if self.extra:
            payload.update(self.extra)
        return payload


class RuntimeEventRecorder:
    """Emits runtime and security events to a logger and keeps a bounded buffer.

    The buffer exists so tests and the API can assert on what happened without
    scraping logs. It is per-instance, never global, and never persisted.
    """

    def __init__(self, log: logging.Logger | None = None, buffer_limit: int = 500) -> None:
        self.log = log or logger
        self.buffer_limit = buffer_limit
        self.events: list[RuntimeEvent] = []
        self.security_events: list[RuntimeEvent] = []

    def emit(
        self,
        event: RuntimeEventType,
        *,
        user_id: EntityId | None = None,
        agent_id: EntityId | None = None,
        agent_run_id: EntityId | None = None,
        runtime_id: EntityId | None = None,
        sandbox_id: str | None = None,
        tool_id: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        duration_seconds: float | None = None,
        exit_code: int | None = None,
        detail: str = "",
        **extra: Any,
    ) -> RuntimeEvent:
        from app.domain.entities._common import utc_now

        if not isinstance(detail, str):
            detail = json.dumps(detail, default=str)
        record = RuntimeEvent(
            event=event.value,
            timestamp=utc_now().isoformat(),
            user_id=str(user_id) if user_id else None,
            agent_id=str(agent_id) if agent_id else None,
            agent_run_id=str(agent_run_id) if agent_run_id else None,
            runtime_id=str(runtime_id) if runtime_id else None,
            sandbox_id=sandbox_id,
            tool_id=tool_id,
            provider=provider,
            status=status,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
            detail=detail,
            extra=redact(extra),
        )
        self._record(record)
        self.log.info("%s", json.dumps(record.as_dict(), default=str))
        return record

    def security(
        self,
        event: SecurityEventType,
        *,
        user_id: EntityId | None = None,
        agent_id: EntityId | None = None,
        agent_run_id: EntityId | None = None,
        runtime_id: EntityId | None = None,
        sandbox_id: str | None = None,
        tool_id: str | None = None,
        detail: str = "",
        **extra: Any,
    ) -> RuntimeEvent:
        record = self.emit(
            RuntimeEventType.RUNTIME_BLOCKED if event.name == "POLICY_VIOLATION" else _SECURITY_MIRROR,
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            runtime_id=runtime_id,
            sandbox_id=sandbox_id,
            tool_id=tool_id,
            detail=detail,
            security_event=event.value,
            **extra,
        )
        self.security_events.append(record)
        if len(self.security_events) > self.buffer_limit:
            del self.security_events[: -self.buffer_limit]
        self.log.warning("security_event=%s %s", event.value, json.dumps(record.as_dict(), default=str))
        return record

    def _record(self, record: RuntimeEvent) -> None:
        self.events.append(record)
        if len(self.events) > self.buffer_limit:
            del self.events[: -self.buffer_limit]

    def clear(self) -> None:
        self.events.clear()
        self.security_events.clear()

    def of_type(self, event: RuntimeEventType) -> list[RuntimeEvent]:
        return [record for record in self.events if record.event == event.value]

    def security_of_type(self, event: SecurityEventType) -> list[RuntimeEvent]:
        return [record for record in self.security_events if record.extra.get("security_event") == event.value]


_SECURITY_MIRROR = RuntimeEventType.RUNTIME_BLOCKED
