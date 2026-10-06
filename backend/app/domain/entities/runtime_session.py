"""A sandboxed execution environment owned by exactly one AgentRun.

Ownership is the isolation unit: ``user_id``/``agent_id``/``agent_run_id`` are
recorded at creation and every access is checked against them, so a runtime
created for run A can never be reached through run B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState


@dataclass
class RuntimeSession:
    agent_id: EntityId
    agent_run_id: EntityId
    provider: RuntimeProvider
    policy: RuntimePolicy
    user_id: EntityId | None = None
    workspace_path: str = ""
    sandbox_id: str | None = None
    state: RuntimeState = RuntimeState.CREATED
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.workspace_path, "workspace_path")
        if self.expires_at.tzinfo is None:
            self.expires_at = self.expires_at.replace(tzinfo=utc_now().tzinfo)

    # -- ownership ---------------------------------------------------------

    def is_owned_by(
        self,
        user_id: EntityId | None,
        agent_id: EntityId,
        agent_run_id: EntityId,
    ) -> bool:
        """All three identifiers must match exactly.

        The user comparison is strict equality in both directions. Treating a
        missing caller identity as "any user" would let a request that never
        authenticated reach a run that belongs to somebody else, which is the
        opposite of what ownership is for.
        """
        return (
            self.agent_run_id == agent_run_id
            and self.agent_id == agent_id
            and self.user_id == user_id
        )

    def assert_owned_by(
        self,
        user_id: EntityId | None,
        agent_id: EntityId,
        agent_run_id: EntityId,
    ) -> None:
        if not self.is_owned_by(user_id, agent_id, agent_run_id):
            raise PermissionError("runtime session belongs to a different agent run")

    def assert_execution_target(
        self,
        agent_run_id: EntityId,
        user_id: EntityId | None,
    ) -> None:
        """Assert that an execution request is aimed at *this* session.

        ``ExecutionRequest`` carries only the run it claims to act for, so the
        agent identity cannot come from the caller and is not re-checked here; a
        run identifier determines its agent by construction. Caller identity is
        compared only when both sides know it, because an internal call path may
        legitimately omit it while a request that *does* name a different user is
        still a cross-session access attempt.
        """
        if self.agent_run_id != agent_run_id:
            raise PermissionError("runtime session belongs to a different agent run")
        if user_id is not None and self.user_id is not None and self.user_id != user_id:
            raise PermissionError("runtime session belongs to a different user")

    # -- lifecycle ---------------------------------------------------------

    def set_state(self, state: RuntimeState) -> None:
        self.state = state
        self.updated_at = utc_now()
        if state is RuntimeState.READY and self.started_at is None:
            self.started_at = self.updated_at
        if state in {RuntimeState.STOPPED, RuntimeState.EXPIRED, RuntimeState.FAILED}:
            self.stopped_at = self.updated_at

    def attach_sandbox(self, sandbox_id: str) -> None:
        self.sandbox_id = sandbox_id
        self.updated_at = utc_now()

    def record_failure(self, reason: str) -> None:
        self.last_error = reason
        self.updated_at = utc_now()

    # -- execution accounting ----------------------------------------------

    #: ``metadata`` key holding how many executions this session has served.
    #:
    #: Kept in ``metadata`` rather than as a column because it is a counter, not
    #: part of the session's identity, and ``metadata`` already round-trips
    #: through persistence. Adding a column for it would mean a migration for no
    #: gain.
    EXECUTION_COUNT_KEY = "execution_count"

    @property
    def execution_count(self) -> int:
        """How many executions have been granted so far.

        Persisted values are data, not trusted code, so the type is checked. A
        corrupt row must not read as zero and quietly restore an unbounded budget.
        """
        value = self.metadata.get(self.EXECUTION_COUNT_KEY, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    def record_execution(self) -> int:
        """Count one granted execution and return the new total."""
        self.metadata[self.EXECUTION_COUNT_KEY] = self.execution_count + 1
        self.updated_at = utc_now()
        return self.metadata[self.EXECUTION_COUNT_KEY]

    def has_execution_budget(self, limit: int) -> bool:
        return self.execution_count < limit

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or utc_now()
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=current.tzinfo)
        return current > expires

    def remaining_seconds(self, now: datetime | None = None) -> float:
        current = now or utc_now()
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=current.tzinfo)
        return max(0.0, (expires - current).total_seconds())

    def extend(self, seconds: int) -> None:
        self.expires_at = utc_now() + timedelta(seconds=seconds)
        self.updated_at = self.expires_at

    def can_execute(self, now: datetime | None = None) -> bool:
        return self.state.accepts_execution and not self.is_expired(now)

    def describe(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "agent_id": str(self.agent_id),
            "agent_run_id": str(self.agent_run_id),
            "provider": self.provider.value,
            "state": self.state.value,
            "sandbox_id": self.sandbox_id,
            "workspace_path": self.workspace_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "expired": self.is_expired(),
            "last_error": self.last_error,
            "policy": self.policy.describe(),
            "metadata": self.metadata,
        }
