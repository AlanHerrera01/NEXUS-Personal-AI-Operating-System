"""Runtime lifecycle coordination.

This is the single place where a sandbox is created, used and torn down. It
holds the invariants that make the layer safe:

1. No TrustEngine ALLOW means no execution (``ExecutionAuthorization`` required).
2. No valid runtime means no execution (``health()`` failure is surfaced, never
   worked around by running on the host).
3. No runtime policy means no privileged execution (``is_isolation_intact``).

It never mutates ``AgentRun``. The orchestrator owns run state; this service
reports outcomes back to the application layer, which decides what to do next.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from app.application.agent_runtime.events import RuntimeEventRecorder
from app.application.agent_runtime.workspace import WorkspaceLayout
from app.domain.entities._common import utc_now
from app.domain.entities.runtime_session import RuntimeSession
from app.domain.ports.agent_runtime import (
    AgentRuntimePort,
    ExecutionRequest,
    RuntimeHealth,
    RuntimePolicyRejectedError,
    RuntimeUnavailableError,
    SandboxHandle,
    SandboxSpec,
    sandbox_labels,
    truncate_output,
)
from app.domain.repositories.runtime_session_repository import RuntimeSessionRepository
from app.domain.services.runtime_state_service import RuntimeStateService
from app.domain.value_objects.command_policy import CommandPolicy
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.execution_authorization import (
    AuthorizationError,
    ExecutionAuthorization,
)
from app.domain.value_objects.runtime_event_type import RuntimeEventType, SecurityEventType
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState

logger = logging.getLogger(__name__)

#: Environment variable names that carry credential material.
#:
#: Matched by exact name, not by substring, so an unrelated variable such as
#: ``TOKENIZER_PATH`` is not mistaken for a secret and blocked by accident. The
#: list is a *deny* trigger for runtimes whose policy forbids secret exposure.
CREDENTIAL_ENV_NAMES: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "COHERE_API_KEY",
        "DATABASE_URL",
        "GEMINI_API_KEY",
        "GITHUB_TOKEN",
        "GOOGLE_API_KEY",
        "HF_TOKEN",
        "NEXUS_CRED",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "PRIVATE_KEY",
        "SSH_KEY",
        "STRIPE_SECRET_KEY",
    }
)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What the application layer needs to know after a sandboxed execution."""

    tool_name: str
    succeeded: bool
    output: str = ""
    error: str | None = None
    exit_code: int = 0
    duration_seconds: float = 0.0
    truncated: bool = False
    runtime_session_id: EntityId | None = None
    sandbox_id: str | None = None
    events: tuple[RuntimeEventType, ...] = ()

    def to_observation(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.succeeded,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 4),
            "truncated": self.truncated,
            "runtime_session_id": str(self.runtime_session_id) if self.runtime_session_id else None,
            "sandbox_id": self.sandbox_id,
        }


class AgentRuntimeService:
    """Owns CREATE → INITIALIZE → APPLY POLICY → START → EXECUTE → CLEANUP → STOP."""

    def __init__(
        self,
        runtime: AgentRuntimePort,
        session_repository: RuntimeSessionRepository,
        command_policy: CommandPolicy,
        workspace: WorkspaceLayout,
        events: RuntimeEventRecorder | None = None,
        state_service: RuntimeStateService | None = None,
    ) -> None:
        self.runtime = runtime
        self.session_repository = session_repository
        self.command_policy = command_policy
        self.workspace = workspace
        self.events = events or RuntimeEventRecorder()
        self.state_service = state_service or RuntimeStateService()

    @property
    def provider(self) -> RuntimeProvider:
        return self.runtime.provider

    async def health(self) -> RuntimeHealth:
        return await self.runtime.health()

    # -- lifecycle ---------------------------------------------------------

    async def start_session(
        self,
        *,
        agent_id: EntityId,
        agent_run_id: EntityId,
        policy: RuntimePolicy,
        user_id: EntityId | None = None,
        image: str | None = None,
    ) -> RuntimeSession:
        """Create a sandbox owned by exactly one agent run."""
        if not policy.is_isolation_intact():
            reason = "runtime policy would not preserve isolation"
            self.events.security(
                SecurityEventType.POLICY_VIOLATION,
                user_id=user_id,
                agent_id=agent_id,
                agent_run_id=agent_run_id,
                detail=reason,
            )
            raise RuntimePolicyRejectedError(reason)

        health = await self.runtime.health()
        if not health.available:
            self.events.emit(
                RuntimeEventType.RUNTIME_UNAVAILABLE,
                user_id=user_id,
                agent_id=agent_id,
                agent_run_id=agent_run_id,
                provider=health.provider,
                detail=health.detail,
            )
            raise RuntimeUnavailableError(health.detail or "agent runtime is unavailable")

        workspace_path = self.workspace.prepare(agent_run_id)
        scoped = policy.with_workspace(workspace_path)

        session = RuntimeSession(
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            provider=health.provider,
            policy=scoped,
            workspace_path=workspace_path,
            expires_at=utc_now() + timedelta(seconds=scoped.expiration_seconds),
        )
        self.session_repository.save(session)
        self.events.emit(
            RuntimeEventType.RUNTIME_CREATED,
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            runtime_id=session.id,
            provider=health.provider,
        )

        spec = SandboxSpec(
            name=self.workspace.sandbox_name(agent_run_id),
            workspace_path=workspace_path,
            image=image,
            labels=sandbox_labels(user_id, agent_id, agent_run_id, session.id),
            cpu=scoped.resources.max_cpu,
            memory=f"{scoped.resources.max_memory_mb}Mi",
        )

        self.state_service.transition(session, RuntimeState.INITIALIZING)
        try:
            handle = await self.runtime.create(spec, scoped)
        except Exception as error:
            session.record_failure("sandbox creation failed")
            self.state_service.transition(session, RuntimeState.FAILED)
            self.session_repository.save(session)
            self.events.emit(
                RuntimeEventType.RUNTIME_EXECUTION_FAILED,
                user_id=user_id,
                agent_id=agent_id,
                agent_run_id=agent_run_id,
                runtime_id=session.id,
                detail="sandbox creation failed",
            )
            raise RuntimeUnavailableError("sandbox creation failed") from error

        session.attach_sandbox(handle.sandbox_id)
        self.session_repository.save(session)
        self.events.emit(
            RuntimeEventType.RUNTIME_POLICY_APPLIED,
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            runtime_id=session.id,
            detail=scoped.describe(),
        )

        try:
            await self.runtime.apply_policy(handle, scoped)
            await self.runtime.start(handle)
        except RuntimePolicyRejectedError:
            self.state_service.transition(session, RuntimeState.BLOCKED)
            session.record_failure("policy rejected by runtime")
            self.session_repository.save(session)
            self.events.emit(
                RuntimeEventType.RUNTIME_POLICY_REJECTED,
                user_id=user_id,
                agent_id=agent_id,
                agent_run_id=agent_run_id,
                runtime_id=session.id,
            )
            self.events.security(
                SecurityEventType.POLICY_VIOLATION,
                user_id=user_id,
                agent_id=agent_id,
                agent_run_id=agent_run_id,
                runtime_id=session.id,
                detail="runtime rejected the policy",
            )
            await self.runtime.cleanup(handle)
            raise
        except Exception as error:
            self.state_service.transition(session, RuntimeState.FAILED)
            session.record_failure("sandbox start failed")
            self.session_repository.save(session)
            await self.runtime.cleanup(handle)
            raise RuntimeUnavailableError("sandbox start failed") from error

        self.state_service.transition(session, RuntimeState.READY)
        self.session_repository.save(session)
        self.events.emit(
            RuntimeEventType.RUNTIME_STARTED,
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            runtime_id=session.id,
            sandbox_id=handle.sandbox_id,
        )
        return session

    async def execute(
        self,
        session: RuntimeSession,
        request: ExecutionRequest,
        authorization: ExecutionAuthorization,
        user_id: EntityId | None = None,
    ) -> ExecutionOutcome:
        """Run one authorized action inside the session's sandbox."""
        outcome = self._pre_execution_checks(session, request, authorization, user_id)
        if outcome is not None:
            return outcome

        # Burn the authorization now that every check has passed. Consuming later
        # than this leaves a window in which the same ALLOW could be replayed.
        authorization.consume()

        handle = self._handle(session)
        session.record_execution()
        self.state_service.transition(session, RuntimeState.RUNNING)
        self.session_repository.save(session)
        self.events.emit(
            RuntimeEventType.RUNTIME_EXECUTION_STARTED,
            user_id=user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
            sandbox_id=session.sandbox_id,
            tool_id=request.tool_name,
        )

        timeout = min(request.timeout_seconds, session.policy.resources.max_execution_seconds)
        bounded = replace(request, timeout_seconds=timeout)
        started = time.monotonic()
        try:
            raw = await self.runtime.execute(handle, bounded, session.policy)
        except Exception as error:  # noqa: BLE001 - never fall back to the host
            timed_out = isinstance(error, TimeoutError) or type(error).__name__ in {
                "TimeoutError",
                "SandboxTimeoutError",
            }
            self.state_service.transition(session, RuntimeState.FAILED)
            session.record_failure("execution failed")
            self.session_repository.save(session)
            # RUNTIME_TIMEOUT existed as an enum member that nothing could ever
            # emit, so a run killed at the limit looked identical to any other
            # failure. It is distinguishable now.
            if timed_out:
                self.events.emit(
                    RuntimeEventType.RUNTIME_TIMEOUT,
                    user_id=user_id,
                    agent_id=session.agent_id,
                    agent_run_id=session.agent_run_id,
                    runtime_id=session.id,
                    sandbox_id=session.sandbox_id,
                    tool_id=request.tool_name,
                    detail=f"exceeded {bounded.timeout_seconds:.1f}s",
                    duration_seconds=round(time.monotonic() - started, 4),
                )
            self.events.emit(
                RuntimeEventType.RUNTIME_EXECUTION_FAILED,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=type(error).__name__,
            )
            return ExecutionOutcome(
                tool_name=request.tool_name,
                succeeded=False,
                error="RUNTIME_TIMEOUT" if timed_out else "RUNTIME_EXECUTION_FAILED",
                runtime_session_id=session.id,
                sandbox_id=session.sandbox_id,
                events=(
                    (RuntimeEventType.RUNTIME_TIMEOUT, RuntimeEventType.RUNTIME_EXECUTION_FAILED)
                    if timed_out
                    else (RuntimeEventType.RUNTIME_EXECUTION_FAILED,)
                ),
            )

        duration = time.monotonic() - started
        stdout, truncated = truncate_output(raw.stdout, session.policy.resources.max_output_bytes)
        stderr, _ = truncate_output(raw.stderr, session.policy.resources.max_output_bytes)

        if session.state is RuntimeState.RUNNING:
            self.state_service.transition(session, RuntimeState.READY)
        self.session_repository.save(session)

        event = (
            RuntimeEventType.RUNTIME_EXECUTION_COMPLETED
            if raw.succeeded
            else RuntimeEventType.RUNTIME_EXECUTION_FAILED
        )
        self.events.emit(
            event,
            user_id=user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
            sandbox_id=session.sandbox_id,
            tool_id=request.tool_name,
            status="SUCCESS" if raw.succeeded else "FAILED",
            duration_seconds=round(duration, 4),
            exit_code=raw.exit_code,
        )
        return ExecutionOutcome(
            tool_name=request.tool_name,
            succeeded=raw.succeeded,
            output=stdout,
            error=None if raw.succeeded else (stderr.strip() or f"exit code {raw.exit_code}"),
            exit_code=raw.exit_code,
            duration_seconds=duration,
            truncated=truncated,
            runtime_session_id=session.id,
            sandbox_id=session.sandbox_id,
            events=(event,),
        )

    async def stop_session(
        self,
        session: RuntimeSession,
        user_id: EntityId | None = None,
        destroy_workspace: bool = False,
    ) -> None:
        """Tear the sandbox down. Cleanup is attempted from every state."""
        if session.sandbox_id:
            handle = self._handle(session)
            if session.state in {RuntimeState.STOPPED, RuntimeState.EXPIRED, RuntimeState.FAILED}:
                await self.runtime.cleanup(handle)
            else:
                if session.state in {
                    RuntimeState.READY,
                    RuntimeState.RUNNING,
                    RuntimeState.WAITING,
                }:
                    self.state_service.transition(session, RuntimeState.STOPPING)
                    self.session_repository.save(session)
                try:
                    await self.runtime.stop(handle)
                except Exception:  # noqa: BLE001 - teardown continues regardless
                    logger.warning("runtime stop failed for session %s", session.id)
                await self.runtime.cleanup(handle)
                self.state_service.transition(session, RuntimeState.STOPPED)

        self.session_repository.save(session)
        if destroy_workspace:
            self.workspace.discard(session.agent_run_id)
        self.events.emit(
            RuntimeEventType.RUNTIME_STOPPED,
            user_id=user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
            sandbox_id=session.sandbox_id,
        )
        self.events.emit(
            RuntimeEventType.RUNTIME_CLEANED_UP,
            user_id=user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
        )

    async def get_session_for_run(self, agent_run_id: EntityId) -> RuntimeSession | None:
        sessions = self.session_repository.get_by_run_id(agent_run_id)
        if not sessions:
            return None
        active = [session for session in sessions if not session.state.is_terminal]
        pool = active or sessions
        return max(pool, key=lambda session: session.created_at)

    async def expire_stale_sessions(self, limit: int = 100) -> int:
        """Reap abandoned runtimes. A sandbox is never left behind."""
        expired = 0
        for state in (
            RuntimeState.INITIALIZING,
            RuntimeState.READY,
            RuntimeState.RUNNING,
            RuntimeState.WAITING,
        ):
            for session in self.session_repository.list_by_state(state)[:limit]:
                if session.is_expired():
                    self.state_service.transition(session, RuntimeState.EXPIRED)
                    self.session_repository.save(session)
                    await self.stop_session(session)
                    expired += 1
        return expired

    # -- internals ---------------------------------------------------------

    def _pre_execution_checks(
        self,
        session: RuntimeSession,
        request: ExecutionRequest,
        authorization: ExecutionAuthorization,
        user_id: EntityId | None,
    ) -> ExecutionOutcome | None:
        """Returns a refusal outcome, or None when execution may proceed."""
        try:
            # Ownership first: without this a caller holding a valid authorization
            # for run A could aim it at run B's sandbox.
            session.assert_execution_target(request.agent_run_id, user_id)
            authorization.assert_valid_for(
                session.agent_id, session.agent_run_id, request.tool_name
            )
            if authorization.is_consumed():
                raise AuthorizationError("authorization has already been used")
        except AuthorizationError as error:
            self.events.security(
                SecurityEventType.MISSING_AUTHORIZATION,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=str(error),
            )
            return self._refuse(session, request.tool_name, f"AUTHORIZATION_DENIED: {error}")
        except PermissionError as error:
            self.events.security(
                SecurityEventType.CROSS_SESSION_ACCESS_DENIED,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=str(error),
            )
            return self._refuse(
                session, request.tool_name, f"CROSS_SESSION_DENIED: {error}"
            )

        if not session.policy.is_isolation_intact():
            self.events.security(
                SecurityEventType.POLICY_VIOLATION,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail="runtime policy is not intact",
            )
            return self._refuse(
                session, request.tool_name, "POLICY_DENIED: runtime policy is not intact"
            )

        if session.is_expired():
            self.state_service.transition(session, RuntimeState.EXPIRED)
            self.session_repository.save(session)
            self.events.emit(
                RuntimeEventType.RUNTIME_EXPIRED,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
            )
            self.events.security(
                SecurityEventType.EXPIRED_RUNTIME_EXECUTION,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
            )
            return ExecutionOutcome(
                tool_name=request.tool_name,
                succeeded=False,
                error="RUNTIME_EXPIRED: no execution",
                runtime_session_id=session.id,
                events=(RuntimeEventType.RUNTIME_EXPIRED,),
            )

        if not session.policy.allows_path(request.working_directory):
            self.events.security(
                SecurityEventType.UNAUTHORIZED_FILESYSTEM_ACCESS,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail="working directory is outside the workspace",
            )
            return self._refuse(
                session, request.tool_name, "FILESYSTEM_DENIED: outside the workspace"
            )

        network_refusal = self._check_network(session, request, user_id)
        if network_refusal is not None:
            return network_refusal

        credential_refusal = self._check_credentials(session, request, user_id)
        if credential_refusal is not None:
            return credential_refusal

        if not session.policy.allows_binary(request.command[0] if request.command else ""):
            self.events.security(
                SecurityEventType.FORBIDDEN_PROCESS,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail="binary is not in the runtime allowlist",
            )
            return self._refuse(
                session, request.tool_name, "PROCESS_DENIED: binary is not allowlisted"
            )

        if not session.has_execution_budget(session.policy.resources.max_tool_calls):
            self.events.security(
                SecurityEventType.RESOURCE_LIMIT_EXCEEDED,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=(
                    f"session has served {session.execution_count} executions, "
                    f"limit is {session.policy.resources.max_tool_calls}"
                ),
            )
            return self._refuse(
                session,
                request.tool_name,
                "RESOURCE_LIMIT_EXCEEDED: tool call budget for this session is spent",
            )

        if not session.state.accepts_execution:
            return self._refuse(session, request.tool_name, f"RUNTIME_NOT_READY: {session.state.value}")

        decision = self.command_policy.validate(
            request.command,
            working_directory=request.working_directory,
            workspace_path=session.workspace_path,
        )
        if not decision.allowed:
            self.events.security(
                SecurityEventType.FORBIDDEN_PROCESS,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=decision.reason,
            )
            return self._refuse(session, request.tool_name, f"COMMAND_DENIED: {decision.reason}")

        return None

    def _check_network(
        self,
        session: RuntimeSession,
        request: ExecutionRequest,
        user_id: EntityId | None,
    ) -> ExecutionOutcome | None:
        """Enforce ``NetworkPolicy`` before the process starts.

        ``allows_endpoint`` used to be reachable only from tests, which made a
        ``DENY`` policy a description rather than a control. The declared
        destinations are checked here so the refusal is ours and is attributable
        to a run; the adapter's socket-level enforcement remains the backstop.
        """
        endpoints = request.network_endpoints

        if len(endpoints) > session.policy.resources.max_network_requests:
            self.events.security(
                SecurityEventType.RESOURCE_LIMIT_EXCEEDED,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=(
                    f"{len(endpoints)} declared destinations exceed "
                    f"max_network_requests={session.policy.resources.max_network_requests}"
                ),
            )
            return self._refuse(
                session,
                request.tool_name,
                "RESOURCE_LIMIT_EXCEEDED: too many network destinations declared",
            )

        for host, port in endpoints:
            if session.policy.allows_endpoint(host, port):
                continue
            # The host is a policy decision input, not payload; a blocked name is
            # safe to record and is needed to explain the refusal. Everything else
            # (paths, credentials, arguments) stays out of the event.
            self.events.security(
                SecurityEventType.BLOCKED_NETWORK_REQUEST,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail=f"destination not permitted: {host}:{port}",
            )
            return self._refuse(
                session,
                request.tool_name,
                f"NETWORK_DENIED: destination not permitted: {host}:{port}",
            )

        if endpoints and not session.policy.network.is_restricted:
            self.events.security(
                SecurityEventType.BLOCKED_NETWORK_REQUEST,
                user_id=user_id,
                agent_id=session.agent_id,
                agent_run_id=session.agent_run_id,
                runtime_id=session.id,
                tool_id=request.tool_name,
                detail="network is denied but the request declares destinations",
            )
            return self._refuse(
                session, request.tool_name, "NETWORK_DENIED: network access is denied"
            )

        return None

    def _check_credentials(
        self,
        session: RuntimeSession,
        request: ExecutionRequest,
        user_id: EntityId | None,
    ) -> ExecutionOutcome | None:
        """Refuse credential material reaching a runtime that may not see it.

        ``is_isolation_intact`` already refuses to *start* a session whose policy
        exposes secrets, so on the live path this is a backstop. It still matters:
        a session restored from the database carries whatever policy was persisted
        with it, and that persisted policy is data, not code. Variable *names* are
        reported; values never appear in the event, the outcome or any log line.
        """
        credentials = session.policy.credentials
        if credentials.exposes_secrets_to_runtime:
            return None

        offending = sorted(
            name
            for name in request.environment
            if name.strip().upper() in CREDENTIAL_ENV_NAMES
        )
        if not offending:
            return None

        # The names are safe to record and are the whole point of the audit
        # trail; the values stay put.
        self.events.security(
            SecurityEventType.CREDENTIAL_ACCESS_DENIED,
            user_id=user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
            tool_id=request.tool_name,
            detail=(
                "credential-shaped variables were supplied to a runtime whose policy "
                "does not expose secrets"
            ),
            credential_names=offending,
        )
        return self._refuse(
            session,
            request.tool_name,
            "CREDENTIAL_DENIED: this runtime's policy does not expose secrets",
        )

    def _refuse(self, session: RuntimeSession, tool_name: str, reason: str) -> ExecutionOutcome:
        self._block(session, reason)
        return ExecutionOutcome(
            tool_name=tool_name,
            succeeded=False,
            error=reason,
            runtime_session_id=session.id,
            events=(RuntimeEventType.RUNTIME_BLOCKED,),
        )

    def _block(self, session: RuntimeSession, reason: str) -> None:
        session.record_failure(reason)
        if not session.state.is_terminal:
            self.state_service.transition(session, RuntimeState.BLOCKED)
        self.session_repository.save(session)
        self.events.emit(
            RuntimeEventType.RUNTIME_BLOCKED,
            user_id=session.user_id,
            agent_id=session.agent_id,
            agent_run_id=session.agent_run_id,
            runtime_id=session.id,
            detail=reason,
        )

    def _handle(self, session: RuntimeSession) -> SandboxHandle:
        return SandboxHandle(
            sandbox_id=session.sandbox_id or "",
            provider=session.provider,
            name=self.workspace.sandbox_name(session.agent_run_id),
            workspace_path=session.workspace_path,
        )
