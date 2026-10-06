"""Proof that the Trust Engine allowed one specific action, exactly once.

The orchestrator mints this only after a ``PermissionDecision.ALLOW``. The
runtime service refuses to execute without a valid, unexpired token bound to
the same agent run and tool. This is what closes the gap where a ``ToolExecutor``
could not previously tell an approved call from an unapproved one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision


class AuthorizationError(PermissionError):
    """Raised when an execution is attempted without a valid authorization."""


@dataclass(slots=True)
class ExecutionAuthorization:
    agent_id: EntityId
    agent_run_id: EntityId
    tool_name: str
    decision: PermissionDecision
    policy_id: str = ""
    user_id: EntityId | None = None
    nonce: str = field(default_factory=lambda: uuid4().hex)
    issued_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    ttl_seconds: int = 300
    #: Set by :meth:`consume`. Guards against replay inside this process; the
    #: durable cross-process guard is the unique index on the persisted nonce.
    consumed_at: datetime | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        require_text(self.tool_name, "tool_name")
        if self.decision is not PermissionDecision.ALLOW:
            raise AuthorizationError("an authorization cannot be minted from a non-ALLOW decision")

    @classmethod
    def allow(
        cls,
        *,
        agent_id: EntityId,
        agent_run_id: EntityId,
        tool_name: str,
        user_id: EntityId | None = None,
        policy_id: str = "",
        ttl_seconds: int = 300,
    ) -> "ExecutionAuthorization":
        now = utc_now()
        return cls(
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            decision=PermissionDecision.ALLOW,
            user_id=user_id,
            policy_id=policy_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            ttl_seconds=ttl_seconds,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or utc_now()
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=current.tzinfo)
        return current > expires

    def assert_valid_for(
        self,
        agent_id: EntityId,
        agent_run_id: EntityId,
        tool_name: str,
        now: datetime | None = None,
    ) -> None:
        if self.decision is not PermissionDecision.ALLOW:
            raise AuthorizationError(
                f"trust decision {self.decision} does not authorize execution"
            )
        if self.agent_run_id != agent_run_id or self.agent_id != agent_id:
            raise AuthorizationError("authorization is bound to a different agent run")
        if self.tool_name != tool_name:
            raise AuthorizationError(
                f"authorization covers {self.tool_name}, not {tool_name}"
            )
        if self.is_expired(now):
            raise AuthorizationError("authorization has expired")

    def consume(self, now: datetime | None = None) -> None:
        """Burn this authorization. Called once, immediately before dispatch.

        Without this, an ALLOW minted for one call could be replayed for any
        number of later calls with the same arguments.
        """
        current = now or utc_now()
        if self.consumed_at is not None:
            raise AuthorizationError("authorization has already been used")
        self.assert_valid_for(self.agent_id, self.agent_run_id, self.tool_name, current)
        self.consumed_at = current

    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def fingerprint(self) -> str:
        """Stable, non-reversible handle. Safe to log."""
        return f"{self.agent_run_id}:{self.tool_name}:{self.nonce[:8]}"
