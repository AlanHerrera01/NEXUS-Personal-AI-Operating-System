"""Composition root for the agent runtime.

This is the only place that knows which concrete runtime backs the port. Above
this line everything depends on ``AgentRuntimePort``. The provider is selected by
configuration and defaults to something that refuses to run rather than something
that runs without isolation.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from functools import lru_cache
from typing import Mapping

from app.application.agent_runtime.credential_service import CredentialService
from app.application.agent_runtime.events import RuntimeEventRecorder
from app.application.agent_runtime.policy_factory import RuntimeBaseline, RuntimePolicyFactory
from app.application.agent_runtime.runtime_tool_executor import (
    RuntimeToolExecutor,
    SandboxCommand,
)
from app.application.agent_runtime.service import AgentRuntimeService
from app.application.agent_runtime.settings import RuntimeLimitsConfig
from app.application.agent_runtime.workspace import WorkspaceLayout
from app.config.settings import Settings, get_settings
from app.domain.ports.agent_runtime import AgentRuntimePort
from app.domain.ports.credential_provider import (
    CredentialProviderPort,
    DenyAllCredentialProvider,
)
from app.domain.ports.tool import ToolDefinition
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.services.runtime_state_service import RuntimeStateService
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.infrastructure.agent_runtime.adapters.fake_agent_runtime import FakeAgentRuntime
from app.infrastructure.agent_runtime.credentials.providers import (
    EnvironmentCredentialProvider,
    ResolverPlaceholderCredentialProvider,
)
from app.infrastructure.agent_runtime.adapters.local_sandbox_runtime import (
    LocalSandboxRuntime,
)
from app.infrastructure.agent_runtime.adapters.openshell_runtime import (
    OpenShellRuntimeAdapter,
)
from app.infrastructure.persistence.database import SessionFactory

logger = logging.getLogger(__name__)


def runtime_limits(settings: Settings | None = None) -> RuntimeLimitsConfig:
    """Project application settings onto the application-layer limits dataclass."""
    current = settings or get_settings()
    driver_timeout = current.runtime_command_timeout_seconds
    workload_timeout = current.runtime_max_execution_seconds
    if driver_timeout <= workload_timeout:
        # Failing loudly here beats a runtime whose driver is killed mid-negotiation
        # and reported to the operator as a workload timeout.
        raise RuntimeError(
            f"runtime_command_timeout_seconds ({driver_timeout}) must exceed "
            f"runtime_max_execution_seconds ({workload_timeout}): the driver has to "
            "outlive the workload it carries"
        )
    limits = RuntimeLimitsConfig(
        max_execution_seconds=workload_timeout,
        max_output_bytes=current.runtime_max_output_bytes,
        max_memory_mb=current.runtime_max_memory_mb,
        max_cpu=current.runtime_max_cpu,
        max_filesystem_bytes=current.runtime_max_filesystem_bytes,
        max_network_requests=current.runtime_max_network_requests,
        max_tool_calls=current.runtime_max_tool_calls,
        max_processes=current.runtime_max_processes,
        expiration_seconds=current.runtime_expiration_seconds,
        read_only_paths=_csv(current.runtime_read_only_paths),
        allowed_network_endpoints=_endpoints(current.runtime_allowed_endpoints),
        allowed_binaries=_csv(current.runtime_allowed_binaries),
        command_timeout_seconds=driver_timeout,
    )

    override = _commands(current.runtime_allowed_commands_json)
    if override:
        # An explicit allowlist also replaces the free-argument set, otherwise a
        # narrowed command list would keep treating its flags as file names.
        return replace(
            limits,
            allowed_commands=override,
            free_argument_commands=tuple(override),
        )
    return limits


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _endpoints(raw: str) -> tuple[tuple[str, int, str], ...]:
    """Parses ``host:port:access`` triples."""
    parsed: list[tuple[str, int, str]] = []
    for entry in _csv(raw):
        parts = entry.split(":")
        if len(parts) != 3:
            raise RuntimeError(
                f"invalid runtime_allowed_endpoints entry {entry!r}; expected host:port:access"
            )
        host, port, access = parts
        parsed.append((host, int(port), access))
    return tuple(parsed)


def _commands(raw: str) -> dict[str, list[str]] | None:
    """Parses the optional command allowlist override. Empty means use defaults."""
    if not raw.strip():
        return None
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("runtime_allowed_commands_json must be valid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("runtime_allowed_commands_json must be a JSON object")
    return {str(key): [str(item) for item in value] for key, value in payload.items()}


def build_runtime(settings: Settings | None = None) -> AgentRuntimePort:
    """Pick the runtime adapter named by ``runtime_provider``.

    An unknown provider is a startup error, not a silent substitution: choosing
    a different runtime than the operator configured would change the isolation
    guarantees the whole feature is built on.
    """
    current = settings or get_settings()
    provider = current.runtime_provider
    limits = runtime_limits(current)

    if provider == RuntimeProvider.OPENSHELL:
        return OpenShellRuntimeAdapter(command_timeout=limits.command_timeout_seconds)
    if provider == RuntimeProvider.LOCAL:
        logger.warning(
            "runtime_provider=LOCAL: development runtime selected. It confines work to "
            "the run workspace but provides no kernel-level isolation."
        )
        return LocalSandboxRuntime(
            command_policy=limits.command_policy(),
            command_timeout=limits.command_timeout_seconds,
        )
    if provider == RuntimeProvider.IN_MEMORY:
        return FakeAgentRuntime()

    raise RuntimeError(
        f"unsupported runtime_provider {provider!r}; the runtime must be explicitly configured"
    )


def build_workspace(settings: Settings | None = None) -> WorkspaceLayout:
    current = settings or get_settings()
    return WorkspaceLayout(root=current.runtime_workspace_root)


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntimePort:
    return build_runtime()


def build_runtime_service(settings: Settings | None = None) -> AgentRuntimeService:
    current = settings or get_settings()
    limits = runtime_limits(current)
    repository = _build_repository(current)
    return AgentRuntimeService(
        runtime=build_runtime(current),
        session_repository=repository,
        command_policy=limits.command_policy(),
        workspace=build_workspace(current),
        events=RuntimeEventRecorder(),
        state_service=RuntimeStateService(),
    )


def build_policy_factory(settings: Settings | None = None) -> RuntimePolicyFactory:
    return RuntimePolicyFactory(RuntimeBaseline.from_config(runtime_limits(settings)))


#: Tools that run inside a sandbox instead of the API process.
#:
#: Each entry is a positional template: every ``{name}`` becomes exactly one argv
#: element, so a model-supplied value can never add a flag or a shell operator of
#: its own. The executables are also checked against the runtime binary
#: allowlist, and the resulting argv is validated again by ``CommandPolicy``.
SANDBOXED_TOOLS: dict[str, SandboxCommand] = {
    "shell.ls": SandboxCommand(
        executable="/usr/bin/ls",
        flags=("--long",),
        positionals=("{path}",),
    ),
    "shell.wc": SandboxCommand(
        executable="/usr/bin/wc",
        positionals=("-l", "{path}"),
    ),
}


def build_runtime_tool_executor(
    delegate: ToolExecutor,
    settings: Settings | None = None,
    definitions: Mapping[str, ToolDefinition] | None = None,
) -> RuntimeToolExecutor:
    """Wrap the in-process executor so sandbox-backed tools are isolated.

    ``delegate`` keeps serving every non-sandboxed tool, so nothing about the
    Phases 1-9 behaviour changes. The sandboxed entries in ``SANDBOXED_TOOLS``
    refuse to run at all unless the Trust Engine minted an authorization.

    ``definitions`` is the live tool metadata. It is passed through because
    ``RuntimePolicyFactory.for_tool`` derives the filesystem and network posture
    from the declared definition; dropping it silently downgraded every
    sandboxed tool to the bare baseline policy.
    """
    current = settings or get_settings()
    if not current.runtime_enabled:
        logger.info("runtime_enabled=false: sandboxed tools are not wired")
        return RuntimeToolExecutor(
            runtime_service=build_runtime_service(current),
            policy_factory=build_policy_factory(current),
            delegate=delegate,
            sandboxed_tools={},
            definitions=definitions,
        )
    return RuntimeToolExecutor(
        runtime_service=build_runtime_service(current),
        policy_factory=build_policy_factory(current),
        delegate=delegate,
        sandboxed_tools=SANDBOXED_TOOLS,
        definitions=definitions,
    )


def build_credential_service(settings: Settings | None = None) -> CredentialService:
    """Compose credential custody.

    ``DenyAllCredentialProvider`` is the default and stays in force unless a
    deployment opts in, which is the correct posture: a credential service that
    is wired but backed by nothing cannot leak anything, whereas one that reads
    the process environment by default would.
    """
    current = settings or get_settings()
    provider: CredentialProviderPort = DenyAllCredentialProvider()
    if current.runtime_credential_provider == "environment":
        provider = EnvironmentCredentialProvider()
    elif current.runtime_credential_provider == "resolver_placeholder":
        provider = ResolverPlaceholderCredentialProvider(
            names=tuple(_csv(current.runtime_credential_names))
        )
    elif current.runtime_credential_provider not in {"deny_all", ""}:
        raise RuntimeError(
            f"unsupported runtime_credential_provider "
            f"{current.runtime_credential_provider!r}"
        )
    return CredentialService(provider=provider, events=RuntimeEventRecorder())


def _build_repository(settings: Settings):
    from app.infrastructure.persistence.models.runtime_session_model import (  # noqa: F401
        RuntimeSessionModel,
    )
    from app.infrastructure.persistence.repositories.runtime_session_repository import (
        SqlAlchemyRuntimeSessionRepository,
    )

    return _SelfScopedRepository(SqlAlchemyRuntimeSessionRepository)


class _SelfScopedRepository:
    """Opens and closes its own SQLAlchemy session per operation.

    Runtime cleanup can be triggered outside the request that created the
    session, so the repository cannot borrow a request-scoped session without
    risking a closed-session error mid-teardown.
    """

    def __init__(self, factory: type) -> None:
        self.factory = factory

    def _run(self, operation: str, *args):
        session = SessionFactory()
        try:
            return getattr(self.factory(session), operation)(*args)
        finally:
            session.close()

    def save(self, entity):
        return self._run("save", entity)

    def get_by_id(self, session_id):
        return self._run("get_by_id", session_id)

    def get_by_run_id(self, agent_run_id):
        return self._run("get_by_run_id", agent_run_id)

    def list_by_state(self, state):
        return self._run("list_by_state", state)

    def delete(self, session_id):
        return self._run("delete", session_id)


__all__ = [
    "SANDBOXED_TOOLS",
    "build_credential_service",
    "build_policy_factory",
    "build_runtime",
    "build_runtime_service",
    "build_runtime_tool_executor",
    "build_workspace",
    "get_agent_runtime",
    "runtime_limits",
]