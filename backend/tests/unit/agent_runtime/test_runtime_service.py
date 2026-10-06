from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.application.agent_runtime.events import RuntimeEventRecorder
from app.application.agent_runtime.service import AgentRuntimeService
from app.application.agent_runtime.workspace import WorkspaceLayout
from app.domain.entities._common import utc_now
from app.domain.entities.runtime_session import RuntimeSession
from app.domain.ports.agent_runtime import (
    AgentRuntimePort,
    ExecutionRequest,
    ExecutionResult,
    RuntimeHealth,
    RuntimeStatus,
    SandboxHandle,
    SandboxSpec,
)
from app.domain.repositories.runtime_session_repository import RuntimeSessionRepository
from app.domain.services.runtime_state_service import RuntimeStateService
from app.domain.value_objects.command_policy import CommandPolicy
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.execution_authorization import ExecutionAuthorization
from app.domain.value_objects.network_mode import NetworkMode
from app.domain.value_objects.runtime_policy import (
    CredentialPolicy,
    FilesystemPolicy,
    NetworkEndpoint,
    NetworkPolicy,
    ProcessPolicy,
    ResourceLimits,
    RuntimePolicy,
)
from app.domain.value_objects.runtime_event_type import RuntimeEventType
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState


class InMemorySessionRepository(RuntimeSessionRepository):
    def __init__(self) -> None:
        self.items: dict[EntityId, RuntimeSession] = {}

    def save(self, session: RuntimeSession) -> RuntimeSession:
        self.items[session.id] = session
        return session

    def get_by_id(self, session_id: EntityId) -> RuntimeSession | None:
        return self.items.get(session_id)

    def get_by_run_id(self, agent_run_id: EntityId) -> list[RuntimeSession]:
        return [s for s in self.items.values() if s.agent_run_id == agent_run_id]

    def list_by_state(self, state: RuntimeState) -> list[RuntimeSession]:
        return [s for s in self.items.values() if s.state is state]

    def delete(self, session_id: EntityId) -> None:
        self.items.pop(session_id, None)


class RecordingRuntime(AgentRuntimePort):
    """In-memory runtime that records the order of lifecycle calls."""

    def __init__(self, available: bool = True, fail_on: str | None = None) -> None:
        self.available = available
        self.fail_on = fail_on
        self.calls: list[str] = []
        self.executed: list[ExecutionRequest] = []
        self.session_counter = 0

    @property
    def provider(self) -> RuntimeProvider:
        return RuntimeProvider.IN_MEMORY

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(self.available, RuntimeProvider.IN_MEMORY, "ok")

    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        self.calls.append("create")
        if self.fail_on == "create":
            raise RuntimeError("gateway refused")
        self.session_counter += 1
        return SandboxHandle(
            sandbox_id=f"sandbox-{self.session_counter}",
            provider=RuntimeProvider.IN_MEMORY,
            name=spec.name,
            workspace_path=spec.workspace_path,
        )

    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        self.calls.append("apply_policy")
        if self.fail_on == "apply_policy":
            from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

            raise RuntimePolicyRejectedError("filesystem rules rejected")

    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        self.calls.append("start")
        return handle

    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        self.calls.append("execute")
        self.executed.append(request)
        return ExecutionResult(
            tool_name=request.tool_name,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.01,
        )

    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        return RuntimeStatus(handle.sandbox_id, RuntimeState.READY)

    async def stop(self, handle: SandboxHandle) -> None:
        self.calls.append("stop")

    async def destroy(self, handle: SandboxHandle) -> None:
        self.calls.append("destroy")


def build_service(runtime: RecordingRuntime | None = None, **kwargs) -> tuple[AgentRuntimeService, InMemorySessionRepository]:
    runtime = runtime or RecordingRuntime()
    repository = InMemorySessionRepository()
    workspace = WorkspaceLayout(root=kwargs.pop("workspace_root", "./.test-runtime"))
    policy = kwargs.pop("command_policy", None) or CommandPolicy.from_spec(
        {"ls": ("-la",), "cat": ()}, ("cat",)
    )
    service = AgentRuntimeService(
        runtime=runtime,
        session_repository=repository,
        command_policy=policy,
        workspace=workspace,
        events=kwargs.pop("events", None) or RuntimeEventRecorder(),
        state_service=RuntimeStateService(),
    )
    return service, repository


def authorization(
    run_id: EntityId,
    tool: str = "shell.ls",
    agent_id: EntityId | None = None,
) -> ExecutionAuthorization:
    return ExecutionAuthorization.allow(
        agent_id=agent_id or EntityId.new(),
        agent_run_id=run_id,
        tool_name=tool,
    )


def auth_for(session: RuntimeSession, tool: str = "shell.ls") -> ExecutionAuthorization:
    """An authorization bound to exactly this session's agent and run."""
    return authorization(session.agent_run_id, tool=tool, agent_id=session.agent_id)


def policy(**overrides) -> RuntimePolicy:
    base = RuntimePolicy(
        filesystem=FilesystemPolicy(read_only_paths=("/usr",), read_write_paths=()),
        processes=ProcessPolicy(allowed_binaries=("/usr/bin/ls", "/usr/bin/cat")),
    )
    # ``RuntimePolicy`` is a slotted dataclass, so there is no ``__dict__`` to
    # splat; ``replace`` is the supported way to vary one field.
    return replace(base, **overrides)


class TestLifecycleOrder:
    async def test_full_lifecycle_runs_in_the_documented_order(self) -> None:
        runtime = RecordingRuntime()
        service, repository = build_service(runtime)
        run_id = EntityId.new()

        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )

        assert runtime.calls[:3] == ["create", "apply_policy", "start"]
        assert session.state is RuntimeState.READY
        assert repository.get_by_id(session.id) is session

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )
        assert outcome.succeeded is True

        await service.stop_session(session)
        assert session.state is RuntimeState.STOPPED
        assert "destroy" in runtime.calls

    async def test_workspace_is_scoped_to_the_run(self) -> None:
        service, _ = build_service()
        first, second = EntityId.new(), EntityId.new()

        one = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=first, policy=policy()
        )
        two = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=second, policy=policy()
        )

        assert one.workspace_path != two.workspace_path
        assert str(first) in one.workspace_path
        assert str(second) in two.workspace_path


class TestStartupRefusals:
    async def test_unavailable_runtime_fails_rather_than_running_on_the_host(self) -> None:
        from app.domain.ports.agent_runtime import RuntimeUnavailableError

        runtime = RecordingRuntime(available=False)
        service, _ = build_service(runtime)

        with pytest.raises(RuntimeUnavailableError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=policy()
            )

        assert runtime.calls == []

    async def test_broken_isolation_policy_is_rejected_before_any_call(self) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        runtime = RecordingRuntime()
        service, _ = build_service(runtime)

        leaky = RuntimePolicy(credentials=CredentialPolicy(allow_host_access=True))

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=leaky
            )

        assert runtime.calls == []

    async def test_rejected_policy_destroys_the_sandbox(self) -> None:
        runtime = RecordingRuntime(fail_on="apply_policy")
        service, _ = build_service(runtime)

        with pytest.raises(Exception):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=policy()
            )

        # Leaving a half-configured sandbox behind is a leak, not a nuisance.
        assert "destroy" in runtime.calls

    async def test_failed_creation_is_marked_failed(self) -> None:
        runtime = RecordingRuntime(fail_on="create")
        service, repository = build_service(runtime)

        with pytest.raises(Exception):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=policy()
            )

        stored = list(repository.items.values())
        assert len(stored) == 1
        assert stored[0].state is RuntimeState.FAILED


class TestExecutionRefusals:
    async def ready_session(self, **kwargs):
        service, repository = build_service(**kwargs)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )
        return service, session, run_id

    async def test_missing_authorization_blocks_execution(self) -> None:
        service, session, run_id = await self.ready_session()
        auth = auth_for(session)
        # Forge the "not authorized" case by presenting an already-spent token.
        auth.consume()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth,
        )

        assert outcome.succeeded is False
        assert "AUTHORIZATION_DENIED" in (outcome.error or "")
        assert outcome.events == (RuntimeEventType.RUNTIME_BLOCKED,)
        assert session.state is RuntimeState.BLOCKED

    async def test_authorization_for_another_run_is_refused(self) -> None:
        service, session, run_id = await self.ready_session()
        foreign = authorization(EntityId.new())

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            foreign,
        )

        assert outcome.succeeded is False
        assert "AUTHORIZATION_DENIED" in (outcome.error or "")

    async def test_authorization_for_another_tool_is_refused(self) -> None:
        service, session, run_id = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session, tool="shell.cat"),
        )

        assert outcome.succeeded is False
        assert "AUTHORIZATION_DENIED" in (outcome.error or "")

    async def test_the_same_authorization_cannot_be_replayed(self) -> None:
        service, session, run_id = await self.ready_session()
        auth = auth_for(session)
        request = ExecutionRequest(
            agent_run_id=run_id,
            tool_name="shell.ls",
            command=("/usr/bin/ls", "-la"),
            working_directory=session.workspace_path,
        )

        first = await service.execute(session, request, auth)
        second = await service.execute(session, request, auth)

        assert first.succeeded is True
        assert second.succeeded is False
        assert "AUTHORIZATION_DENIED" in (second.error or "")

    async def test_path_outside_the_workspace_is_refused(self) -> None:
        service, session, run_id = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory="/etc",
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "FILESYSTEM_DENIED" in (outcome.error or "")

    async def test_binary_outside_the_allowlist_is_refused(self) -> None:
        service, session, run_id = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/bin/sh", "-c"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "PROCESS_DENIED" in (outcome.error or "")

    async def test_expired_session_refuses_to_execute(self) -> None:
        service, session, run_id = await self.ready_session()
        session.expires_at = utc_now() - timedelta(seconds=1)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "RUNTIME_EXPIRED" in (outcome.error or "")


class TestLimits:
    async def test_output_is_truncated_to_the_policy_limit(self) -> None:
        service, session, run_id = await self.ready_session_with_output(
            "x" * 10_000, max_output_bytes=1_024
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True
        assert outcome.truncated is True
        assert len(outcome.output.encode()) <= session.policy.resources.max_output_bytes

    async def test_execution_timeout_is_clamped_to_the_policy_limit(self) -> None:
        service, session, run_id = await self.ready_session_with_output("ok")

        await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                timeout_seconds=900,
            ),
            auth_for(session),
        )

        assert service.runtime.executed[0].timeout_seconds == 5

    async def ready_session_with_output(self, stdout: str, max_output_bytes: int = 262_144):
        runtime = RecordingRuntime()

        async def execute(handle, request, policy):
            runtime.executed.append(request)
            return ExecutionResult(
                tool_name=request.tool_name,
                exit_code=0,
                stdout=stdout,
                stderr="",
                duration_seconds=0.0,
            )

        runtime.execute = execute  # type: ignore[method-assign]
        service, _ = build_service(runtime)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(),
            agent_run_id=run_id,
            policy=RuntimePolicy(
                filesystem=FilesystemPolicy(read_only_paths=("/usr",)),
                processes=ProcessPolicy(allowed_binaries=("/usr/bin/ls",)),
                resources=ResourceLimits(
                    max_execution_seconds=5,
                    max_output_bytes=max_output_bytes,
                ),
            ),
        )
        return service, session, run_id


class TestSessionLifecycle:
    async def test_expiry_reaps_abandoned_sandboxes(self) -> None:
        service, repository = build_service()
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )
        session.expires_at = utc_now() - timedelta(seconds=1)

        reaped = await service.expire_stale_sessions()

        assert reaped == 1
        assert repository.get_by_id(session.id).state is RuntimeState.EXPIRED

    async def test_live_sessions_are_not_reaped(self) -> None:
        service, _ = build_service()

        assert await service.expire_stale_sessions() == 0

    def test_terminal_states_are_terminal(self) -> None:
        assert RuntimeState.STOPPED.is_terminal is True
        assert RuntimeState.EXPIRED.is_terminal is True
        assert RuntimeState.FAILED.is_terminal is True
        assert RuntimeState.BLOCKED.is_terminal is True
        assert RuntimeState.READY.is_terminal is False

    def test_only_ready_and_running_accept_execution(self) -> None:
        assert RuntimeState.READY.accepts_execution is True
        assert RuntimeState.RUNNING.accepts_execution is True
        assert RuntimeState.STOPPED.accepts_execution is False
        assert RuntimeState.EXPIRED.accepts_execution is False
        assert RuntimeState.BLOCKED.accepts_execution is False


class TestCrossSessionAccess:
    """A request must be aimed at the sandbox it was authorized for."""

    async def test_a_request_for_another_run_is_refused(self) -> None:
        service, _ = build_service()
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )
        # A valid authorization for this session's own agent and run, but the
        # request claims to act for a different run.
        foreign_run = EntityId.new()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=foreign_run,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "CROSS_SESSION_DENIED" in (outcome.error or "")
        assert service.runtime.executed == []

    async def test_a_request_from_another_user_is_refused(self) -> None:
        service, _ = build_service()
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, user_id=EntityId.new(), policy=policy()
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
            user_id=EntityId.new(),
        )

        assert outcome.succeeded is False
        assert "CROSS_SESSION_DENIED" in (outcome.error or "")
        assert service.runtime.executed == []

    async def test_the_matching_run_and_user_are_accepted(self) -> None:
        service, _ = build_service()
        run_id = EntityId.new()
        user_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, user_id=user_id, policy=policy()
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
            user_id=user_id,
        )

        assert outcome.succeeded is True


class TestNetworkEnforcement:
    """``NetworkPolicy`` is a control, not a description."""

    async def ready_session(self, **overrides):
        runtime = RecordingRuntime()
        service, _ = build_service(runtime)
        run_id = EntityId.new()
        limits = RuntimeLimitsConfigHolder(overrides.pop("limits", {}))
        session = await service.start_session(
            agent_id=EntityId.new(),
            agent_run_id=run_id,
            policy=RuntimePolicy(
                filesystem=FilesystemPolicy(read_only_paths=("/usr",)),
                processes=ProcessPolicy(allowed_binaries=("/usr/bin/ls",)),
                network=overrides.pop("network", NetworkPolicy()),
                resources=limits.build(),
            ),
        )
        return service, session, run_id

    async def test_a_denied_destination_is_refused_before_execution(self) -> None:
        service, session, run_id = await self.ready_session()
        auth = auth_for(session)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("169.254.169.254", 80),),
            ),
            auth,
        )

        assert outcome.succeeded is False
        assert "NETWORK_DENIED" in (outcome.error or "")
        assert service.runtime.executed == []

    async def test_an_allowlisted_destination_is_permitted_when_restricted(self) -> None:
        service, session, run_id = await self.ready_session(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=(NetworkEndpoint("api.internal", 443),),
            )
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("api.internal", 443),),
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True

    async def test_wrong_port_on_an_allowlisted_host_is_refused(self) -> None:
        service, session, run_id = await self.ready_session(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=(NetworkEndpoint("api.internal", 443),),
            )
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("api.internal", 22),),
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "NETWORK_DENIED" in (outcome.error or "")

    async def test_a_host_that_only_similar_is_refused(self) -> None:
        # Substring and suffix matching would both accept this.
        service, session, run_id = await self.ready_session(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=(NetworkEndpoint("api.internal", 443),),
            )
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("evil.api.internal.attacker.test", 443),),
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "NETWORK_DENIED" in (outcome.error or "")

    async def test_declaring_no_destinations_never_blocks_a_local_command(self) -> None:
        service, session, run_id = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True

    async def test_too_many_declared_destinations_hits_the_ceiling(self) -> None:
        service, session, run_id = await self.ready_session(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=tuple(
                    NetworkEndpoint(f"host{i}.internal", 443) for i in range(4)
                ),
            ),
            limits={"max_network_requests": 2},
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(
                    ("host0.internal", 443),
                    ("host1.internal", 443),
                    ("host2.internal", 443),
                ),
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "RESOURCE_LIMIT_EXCEEDED" in (outcome.error or "")

    async def test_endpoints_within_the_ceiling_still_run(self) -> None:
        service, session, run_id = await self.ready_session(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=tuple(
                    NetworkEndpoint(f"host{i}.internal", 443) for i in range(4)
                ),
            ),
            limits={"max_network_requests": 2},
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("host0.internal", 443), ("host1.internal", 443)),
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True


class RuntimeLimitsConfigHolder:
    """Small builder so each test only states the limits it cares about."""

    def __init__(self, overrides: dict) -> None:
        self.overrides = overrides

    def build(self) -> ResourceLimits:
        defaults = {"max_execution_seconds": 30.0, "max_output_bytes": 262_144}
        return ResourceLimits(**{**defaults, **self.overrides})


class TestCredentialContainment:
    """A policy that keeps secrets out must actually keep them out."""

    async def ready_session(self, **credential_overrides):
        runtime = RecordingRuntime()
        events = RuntimeEventRecorder()
        service, _ = build_service(runtime, events=events)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(),
            agent_run_id=run_id,
            policy=policy(credentials=CredentialPolicy(**credential_overrides)),
        )
        return service, session, run_id, events

    async def test_a_credential_in_the_environment_is_refused(self) -> None:
        service, session, run_id, events = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                environment={"OPENAI_API_KEY": "sk-live-should-not-be-here"},
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert "CREDENTIAL_DENIED" in (outcome.error or "")
        assert service.runtime.executed == []

    async def test_the_refusal_records_the_name_but_never_the_value(self) -> None:
        secret = "sk-live-should-not-be-here"
        service, session, run_id, events = await self.ready_session()

        await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                environment={"OPENAI_API_KEY": secret},
            ),
            auth_for(session),
        )

        rendered = " ".join(record.detail for record in events.security_events)
        rendered += " ".join(str(record.extra) for record in events.security_events)
        assert "OPENAI_API_KEY" in rendered
        assert secret not in rendered

    async def test_an_ordinary_environment_passes_through(self) -> None:
        service, session, run_id, _ = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                environment={"LANG": "C.UTF-8", "PATH": "/usr/bin"},
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True

    async def test_a_name_that_merely_looks_secret_is_not_blocked(self) -> None:
        # Matching by substring would block these and break working tools.
        service, session, run_id, _ = await self.ready_session()

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                environment={"TOKENIZER_PATH": "/models/tok", "PASSWORD_POLICY": "strict"},
            ),
            auth_for(session),
        )

        assert outcome.succeeded is True

    async def test_a_policy_permitting_injection_cannot_start_a_session(self) -> None:
        # Stronger than the check above: the session never exists, so there is no
        # environment to smuggle anything through. Credentials reach the egress
        # boundary via CredentialService, never the sandbox.
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        service, _ = build_service()

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(),
                agent_run_id=EntityId.new(),
                policy=policy(credentials=CredentialPolicy(allow_runtime_injection=True)),
            )

    async def test_host_access_cannot_start_a_session_either(self) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        service, _ = build_service()

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(),
                agent_run_id=EntityId.new(),
                policy=policy(credentials=CredentialPolicy(allow_host_access=True)),
            )


class TestToolCallBudget:
    """``max_tool_calls`` was a reported number, not a limit."""

    async def ready_session(self, max_tool_calls: int = 3):
        runtime = RecordingRuntime()
        events = RuntimeEventRecorder()
        service, _ = build_service(runtime, events=events)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(),
            agent_run_id=run_id,
            policy=policy(
                resources=ResourceLimits(
                    max_execution_seconds=30.0,
                    max_output_bytes=262_144,
                    max_tool_calls=max_tool_calls,
                )
            ),
        )
        return service, session, run_id, events

    async def run(self, service, session, run_id):
        return await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

    async def test_calls_up_to_the_limit_succeed(self) -> None:
        service, session, run_id, _ = await self.ready_session(max_tool_calls=3)

        for _ in range(3):
            assert (await self.run(service, session, run_id)).succeeded is True
        assert session.execution_count == 3

    async def test_the_call_after_the_limit_is_refused(self) -> None:
        service, session, run_id, _ = await self.ready_session(max_tool_calls=2)

        for _ in range(2):
            await self.run(service, session, run_id)

        outcome = await self.run(service, session, run_id)

        assert outcome.succeeded is False
        assert "RESOURCE_LIMIT_EXCEEDED" in (outcome.error or "")
        assert len(service.runtime.executed) == 2

    async def test_a_refused_call_is_not_counted(self) -> None:
        # Otherwise a single denied request could exhaust a budget.
        service, session, run_id, _ = await self.ready_session(max_tool_calls=1)

        await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                network_endpoints=(("169.254.169.254", 80),),
            ),
            auth_for(session),
        )

        assert session.execution_count == 0

    async def test_a_zero_budget_blocks_immediately(self) -> None:
        service, session, run_id, _ = await self.ready_session(max_tool_calls=0)

        outcome = await self.run(service, session, run_id)

        assert outcome.succeeded is False
        assert "RESOURCE_LIMIT_EXCEEDED" in (outcome.error or "")
        assert service.runtime.executed == []

    async def test_the_counter_survives_a_persistence_round_trip(self) -> None:
        # The counter lives in metadata, so it must be counted on reload and not
        # restart from zero.
        service, session, run_id, _ = await self.ready_session(max_tool_calls=2)
        await self.run(service, session, run_id)

        reloaded = service.session_repository.get_by_id(session.id)
        assert reloaded is not None
        assert reloaded.execution_count == 1

    async def test_a_corrupt_counter_does_not_restore_an_unbounded_budget(self) -> None:
        service, session, run_id, _ = await self.ready_session(max_tool_calls=1)
        session.metadata[session.EXECUTION_COUNT_KEY] = "many"

        outcome = await self.run(service, session, run_id)

        # Zero, so the budget is intact rather than silently void.
        assert outcome.succeeded is True
        assert session.execution_count == 1


class TestTimeoutReporting:
    """A run killed at the limit must be distinguishable from any other failure."""

    async def test_a_timeout_is_reported_as_a_timeout(self) -> None:
        runtime = RecordingRuntime()

        async def execute(handle, request, policy):
            raise TimeoutError("command exceeded its deadline")

        runtime.execute = execute  # type: ignore[method-assign]
        events = RuntimeEventRecorder()
        service, _ = build_service(runtime, events=events)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.succeeded is False
        assert outcome.error == "RUNTIME_TIMEOUT"
        assert RuntimeEventType.RUNTIME_TIMEOUT in outcome.events
        assert len(events.of_type(RuntimeEventType.RUNTIME_TIMEOUT)) == 1

    async def test_an_ordinary_failure_is_not_reported_as_a_timeout(self) -> None:
        runtime = RecordingRuntime()

        async def execute(handle, request, policy):
            raise RuntimeError("binary vanished")

        runtime.execute = execute  # type: ignore[method-assign]
        events = RuntimeEventRecorder()
        service, _ = build_service(runtime, events=events)
        run_id = EntityId.new()
        session = await service.start_session(
            agent_id=EntityId.new(), agent_run_id=run_id, policy=policy()
        )

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            auth_for(session),
        )

        assert outcome.error == "RUNTIME_EXECUTION_FAILED"
        assert events.of_type(RuntimeEventType.RUNTIME_TIMEOUT) == []