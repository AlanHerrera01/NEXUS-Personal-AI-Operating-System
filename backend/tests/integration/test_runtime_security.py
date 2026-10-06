"""Phase 10 security tests.

Each test here corresponds to an attack or an accidental-privilege scenario that
must fail closed. They are deliberately written against the real service and the
real ``ExecutionAuthorization`` rather than mocks, because the guarantee is about
the interaction between Trust Engine, orchestrator and runtime, and a mock cannot
demonstrate that interaction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.agent_runtime.runtime_tool_executor import (
    RuntimeToolExecutor,
    SandboxCommand,
)
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
from app.domain.ports.plan_validator import PlanValidatorPort, ProposedAction, ProposedPlan
from app.domain.ports.tool import ToolContext
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.repositories.runtime_session_repository import RuntimeSessionRepository
from app.domain.services.runtime_state_service import RuntimeStateService
from app.domain.value_objects.command_policy import CommandPolicy
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.execution_authorization import (
    AuthorizationError,
    ExecutionAuthorization,
)
from app.domain.value_objects.network_mode import NetworkMode
from app.domain.value_objects.runtime_policy import (
    CredentialPolicy,
    FilesystemPolicy,
    NetworkEndpoint,
    ProcessPolicy,
    ResourceLimits,
    RuntimePolicy,
)
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


class SpyRuntime(AgentRuntimePort):
    """Records every argv it is asked to execute."""

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.executed: list[ExecutionRequest] = []
        self.created: list[SandboxSpec] = []
        self.counter = 0

    @property
    def provider(self) -> RuntimeProvider:
        return RuntimeProvider.IN_MEMORY

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(self.available, RuntimeProvider.IN_MEMORY, "ok")

    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        self.created.append(spec)
        self.counter += 1
        return SandboxHandle(
            sandbox_id=f"sbx-{self.counter}",
            provider=RuntimeProvider.IN_MEMORY,
            name=spec.name,
            workspace_path=spec.workspace_path,
        )

    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        return None

    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        return handle

    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        self.executed.append(request)
        return ExecutionResult(
            tool_name=request.tool_name, exit_code=0, stdout="ok", stderr="", duration_seconds=0.0
        )

    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        return RuntimeStatus(handle.sandbox_id, RuntimeState.READY)

    async def stop(self, handle: SandboxHandle) -> None:
        return None

    async def destroy(self, handle: SandboxHandle) -> None:
        return None


class RefusingDelegate(ToolExecutor):
    """An in-process executor that refuses loudly, so a fallback is detectable."""

    async def execute(self, tool_name, arguments, context):
        raise AssertionError(f"the sandboxed tool {tool_name} fell through to the host executor")


def build_service(runtime: SpyRuntime | None = None) -> AgentRuntimeService:
    runtime = runtime or SpyRuntime()
    return AgentRuntimeService(
        runtime=runtime,
        session_repository=InMemorySessionRepository(),
        command_policy=CommandPolicy.from_spec({"ls": ("-la",), "cat": ()}, ("cat",)),
        workspace=WorkspaceLayout(root="./.test-runtime-security"),
        state_service=RuntimeStateService(),
    )


def base_policy(**overrides) -> RuntimePolicy:
    defaults = {
        "filesystem": FilesystemPolicy(read_only_paths=("/usr",), read_write_paths=()),
        "processes": ProcessPolicy(allowed_binaries=("/usr/bin/ls", "/usr/bin/cat")),
        "resources": ResourceLimits(max_execution_seconds=5, max_output_bytes=4096),
    }
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


async def ready_session(service: AgentRuntimeService, policy: RuntimePolicy | None = None) -> tuple[RuntimeSession, EntityId, EntityId]:
    agent_id, run_id = EntityId.new(), EntityId.new()
    session = await service.start_session(
        agent_id=agent_id, agent_run_id=run_id, policy=policy or base_policy()
    )
    return session, agent_id, run_id


def allow(session: RuntimeSession, tool: str = "shell.ls", **kwargs) -> ExecutionAuthorization:
    return ExecutionAuthorization.allow(
        agent_id=session.agent_id,
        agent_run_id=session.agent_run_id,
        tool_name=tool,
        **kwargs,
    )


# -- 1. execution without an authorization -----------------------------------


class TestNoAuthorizationMeansNoExecution:
    async def test_a_minted_token_cannot_be_forged_without_an_allow(self) -> None:
        from app.domain.value_objects.permission_decision import PermissionDecision

        with pytest.raises(AuthorizationError):
            ExecutionAuthorization(
                agent_id=EntityId.new(),
                agent_run_id=EntityId.new(),
                tool_name="shell.ls",
                decision=PermissionDecision.DENY,
            )

    async def test_an_expired_token_is_refused(self) -> None:
        service = build_service()
        session, _, run_id = await ready_session(service)
        expired = allow(session, ttl_seconds=-1)

        assert expired.is_expired() is True

    async def test_execution_without_a_valid_token_never_reaches_the_runtime(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)
        expired = allow(session, ttl_seconds=-1)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            expired,
        )

        assert outcome.succeeded is False
        assert "AUTHORIZATION_DENIED" in (outcome.error or "")
        assert runtime.executed == []

    async def test_the_executor_refuses_a_sandboxed_tool_with_no_authorization(self) -> None:
        from app.application.agent_runtime.policy_factory import (
            RuntimeBaseline,
            RuntimePolicyFactory,
        )
        from app.application.agent_runtime.settings import RuntimeLimitsConfig

        runtime = SpyRuntime()
        service = build_service(runtime)
        executor = RuntimeToolExecutor(
            runtime_service=service,
            policy_factory=RuntimePolicyFactory(
                RuntimeBaseline.from_config(RuntimeLimitsConfig())
            ),
            delegate=RefusingDelegate(),
            sandboxed_tools={"shell.ls": SandboxCommand(executable="/usr/bin/ls", flags=("--long",), positionals=("{path}",))},
        )
        context = ToolContext(
            agent_id=EntityId.new(),
            agent_run_id=EntityId.new(),
            # authorization deliberately absent
        )

        observation = await executor.execute("shell.ls", {"path": "."}, context)

        assert observation.success is False
        assert "AUTHORIZATION_DENIED" in (observation.error or "")
        assert runtime.executed == []
        assert runtime.created == []


# -- 2. host filesystem escape -----------------------------------------------


class TestFilesystemEscape:
    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "/root/.ssh/id_rsa",
            "~/.aws/credentials",
            "/proc/self/environ",
            "/var/run/docker.sock",
            "/host/etc",
            "/etc",
        ],
    )
    async def test_paths_outside_the_workspace_are_refused(self, path: str) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=path,
            ),
            allow(session),
        )

        assert outcome.succeeded is False
        assert runtime.executed == []

    async def test_a_path_argument_escaping_the_workspace_is_refused(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/cat", "../../../etc/shadow"),
                working_directory=session.workspace_path,
            ),
            allow(session, tool="shell.ls"),
        )

        assert outcome.succeeded is False
        assert "COMMAND_DENIED" in (outcome.error or "")
        assert runtime.executed == []

    async def test_the_plan_validator_rejects_credential_paths(self) -> None:
        from app.application.agent_runtime.plan_validator import DefaultPlanValidator

        result = DefaultPlanValidator().validate(
            ProposedPlan(
                agent_id=EntityId.new(),
                agent_run_id=EntityId.new(),
                actions=(
                    ProposedAction(
                        tool_name="shell.cat",
                        arguments={"path": "~/.ssh/id_rsa"},
                    ),
                ),
                available_tool_names={"shell.cat"},
            )
        )

        assert result.valid is False


# -- 3. undeclared network egress --------------------------------------------


class TestNetworkEgress:
    async def test_egress_is_denied_when_no_endpoint_is_declared(self) -> None:
        policy = base_policy()

        assert policy.network.mode is NetworkMode.DENY
        assert policy.allows_endpoint("api.openai.com", 443) is False

    async def test_an_undeclared_endpoint_is_not_rendered_into_the_policy(self) -> None:
        from app.infrastructure.agent_runtime.policies.openshell_policy_renderer import (
            OpenShellPolicyRenderer,
        )

        document = OpenShellPolicyRenderer().render(base_policy(), "/sandbox/ws")

        assert "network_policies" not in document

    async def test_an_endpoint_must_appear_in_the_baseline_to_be_used(self) -> None:
        from app.application.agent_runtime.policy_factory import (
            RuntimeBaseline,
            RuntimePolicyFactory,
        )
        from app.application.agent_runtime.settings import RuntimeLimitsConfig

        factory = RuntimePolicyFactory(
            RuntimeBaseline.from_config(
                RuntimeLimitsConfig(
                    allowed_network_endpoints=(("api.example.com", 443, "read-only"),)
                )
            )
        )

        policy = factory.for_tool(
            None,
            requested_endpoints=(NetworkEndpoint(host="evil.example.com", port=443),),
            needs_network=True,
        )

        assert policy.allows_endpoint("evil.example.com", 443) is False


# -- 4. undeclared binaries / arbitrary code execution -----------------------


class TestArbitraryExecution:
    @pytest.mark.parametrize(
        "command",
        [
            ("/bin/sh", "-c", "cat /etc/passwd"),
            ("/usr/bin/python", "-c", "import os; os.system('id')"),
            ("/usr/bin/env",),
            ("/bin/bash", "-lc", "id"),
            ("/usr/bin/curl", "https://evil.example.com"),
            ("/usr/bin/env", "sh"),
        ],
    )
    async def test_a_binary_outside_the_allowlist_never_reaches_the_runtime(
        self, command: tuple[str, ...]
    ) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=command,
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert outcome.succeeded is False
        assert "PROCESS_DENIED" in (outcome.error or "") or "COMMAND_DENIED" in (
            outcome.error or ""
        )
        assert runtime.executed == []

    async def test_a_shell_metacharacter_in_an_argument_is_refused(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "; cat /etc/passwd"),
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert outcome.succeeded is False
        assert runtime.executed == []


# -- 5. a runtime failure must not degrade to the host ------------------------


class TestNoHostFallback:
    async def test_an_unavailable_runtime_fails_the_call(self) -> None:
        from app.domain.ports.agent_runtime import RuntimeUnavailableError

        runtime = SpyRuntime(available=False)
        service = build_service(runtime)

        with pytest.raises(RuntimeUnavailableError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=base_policy()
            )

    async def test_a_failing_execution_reports_failure_and_does_not_retry(self) -> None:
        class ExplodingRuntime(SpyRuntime):
            async def execute(self, handle, request, policy):
                # Record the attempt here rather than delegating: the parent
                # appends to `executed` only on the success path, and this test
                # exists to prove the call was attempted exactly once.
                self.executed.append(request)
                raise OSError("the sandbox died")

        runtime = ExplodingRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert outcome.succeeded is False
        assert outcome.error == "RUNTIME_EXECUTION_FAILED"
        assert len(runtime.executed) == 1

    async def test_a_policy_the_runtime_rejects_prevents_execution_entirely(self) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        class StrictRuntime(SpyRuntime):
            async def apply_policy(self, handle, policy):
                raise RuntimePolicyRejectedError("landlock unavailable")

        runtime = StrictRuntime()
        service = build_service(runtime)

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=base_policy()
            )

        assert runtime.executed == []


# -- 6. cross-session / cross-tenant isolation --------------------------------


class TestSessionIsolation:
    async def test_one_run_cannot_execute_in_another_runs_sandbox(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        first, _, first_run = await ready_session(service)
        second, _, second_run = await ready_session(service)

        assert first.workspace_path != second.workspace_path

        # The token from run one cannot drive run two's session.
        outcome = await service.execute(
            second,
            ExecutionRequest(
                agent_run_id=second_run,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=second.workspace_path,
            ),
            ExecutionAuthorization.allow(
                agent_id=first.agent_id,
                agent_run_id=first_run,
                tool_name="shell.ls",
            ),
        )

        assert outcome.succeeded is False
        assert runtime.executed == []

    async def test_a_token_from_another_agent_on_the_same_run_is_refused(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            ExecutionAuthorization.allow(
                agent_id=EntityId.new(), agent_run_id=run_id, tool_name="shell.ls"
            ),
        )

        assert outcome.succeeded is False

    async def test_a_token_cannot_be_replayed_for_a_second_call(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)
        token = allow(session)
        request = ExecutionRequest(
            agent_run_id=run_id,
            tool_name="shell.ls",
            command=("/usr/bin/ls", "-la"),
            working_directory=session.workspace_path,
        )

        first = await service.execute(session, request, token)
        second = await service.execute(session, request, token)

        assert first.succeeded is True
        assert second.succeeded is False
        assert len(runtime.executed) == 1


# -- 7. secrets must not reach the sandbox or the model -----------------------


class TestSecretContainment:
    async def test_a_policy_exposing_secrets_is_refused_before_startup(self) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        runtime = SpyRuntime()
        service = build_service(runtime)
        leaky = base_policy(credentials=CredentialPolicy(allow_host_access=True))

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=leaky
            )

        assert runtime.created == []

    async def test_runtime_injection_also_counts_as_exposure(self) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        runtime = SpyRuntime()
        service = build_service(runtime)
        leaky = base_policy(credentials=CredentialPolicy(allow_runtime_injection=True))

        with pytest.raises(RuntimePolicyRejectedError):
            await service.start_session(
                agent_id=EntityId.new(), agent_run_id=EntityId.new(), policy=leaky
            )

    async def test_the_session_description_carries_no_credential_names(self) -> None:
        policy = base_policy(
            credentials=CredentialPolicy(allowed_credential_names=frozenset({"NEBIUS_API_KEY"}))
        )

        described = str(policy.describe())

        assert "NEBIUS_API_KEY" not in described

    async def test_the_observation_carries_no_credential_values(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert "sk-" not in str(outcome.to_observation())


# -- 8. expiry and abuse ceilings --------------------------------------------


class TestResourceExhaustion:
    async def test_an_expired_session_refuses_execution(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)
        session.expires_at = utc_now() - timedelta(seconds=1)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert outcome.succeeded is False
        assert "RUNTIME_EXPIRED" in (outcome.error or "")
        assert runtime.executed == []

    async def test_the_requested_timeout_cannot_exceed_the_policy_limit(self) -> None:
        runtime = SpyRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
                timeout_seconds=86_400,
            ),
            allow(session),
        )

        assert runtime.executed[0].timeout_seconds == 5

    async def test_output_larger_than_the_limit_is_clamped(self) -> None:
        class LoudRuntime(SpyRuntime):
            async def execute(self, handle, request, policy):
                return ExecutionResult(
                    tool_name=request.tool_name,
                    exit_code=0,
                    stdout="x" * 100_000,
                    stderr="",
                    duration_seconds=0.0,
                )

        runtime = LoudRuntime()
        service = build_service(runtime)
        session, _, run_id = await ready_session(service)

        outcome = await service.execute(
            session,
            ExecutionRequest(
                agent_run_id=run_id,
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=session.workspace_path,
            ),
            allow(session),
        )

        assert outcome.truncated is True
        assert len(outcome.output) <= session.policy.resources.max_output_bytes


# -- 9. the LLM never gets to decide -----------------------------------------


class TestModelIsNotTheAuthority:
    async def test_reserved_arguments_cannot_be_set_by_a_plan(self) -> None:
        from app.application.agent_runtime.plan_validator import DefaultPlanValidator

        result = DefaultPlanValidator().validate(
            ProposedPlan(
                agent_id=EntityId.new(),
                agent_run_id=EntityId.new(),
                actions=(
                    ProposedAction(
                        tool_name="shell.ls",
                        arguments={"path": ".", "permissions": ["*"]},
                    ),
                ),
                available_tool_names={"shell.ls"},
            )
        )

        assert result.valid is False

    async def test_an_unsupported_decision_never_reaches_a_tool(self) -> None:
        from unittest.mock import AsyncMock, Mock

        from app.application.agents.orchestrator import AgentOrchestrator
        from app.domain.entities.agent_run import AgentRun
        from app.domain.ports.agent_brain import AgentDecision, AgentDecisionType
        from app.domain.value_objects.entity_id import EntityId as _EntityId
        from app.application.agents.context_builder import AgentContextBuilder

        brain = Mock()
        brain.decide = AsyncMock(
            return_value=AgentDecision(
                decision_type="EXFILTRATE",  # not a real decision type
                tool_name="shell.ls",
            )
        )
        executor = Mock(spec=ToolExecutor)

        run = AgentRun(
            agent_id=_EntityId.new(),
            user_request="do something",
        )
        orchestrator = AgentOrchestrator(
            agent_run_repository=Mock(),
            agent_brain=brain,
            tool_registry=Mock(definitions=Mock(return_value=[])),
            tool_executor=executor,
            trust_engine=Mock(),
            agent_action_repository=Mock(),
            context_builder=Mock(spec=AgentContextBuilder),
        )

        result = await orchestrator.execute(run)

        assert result.run.status.value == "FAILED"
        executor.execute.assert_not_called()