"""The boundary between NEXUS and any sandbox technology.

The interface is derived from the capabilities actually documented for
OpenShell sandboxes (create, apply policy, start, exec, stop, delete, status,
upload, download) and expressed in NEXUS's own vocabulary. No OpenShell, Docker
or NemoClaw type appears here, and none may be imported above ``infrastructure``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState


class RuntimeErrorBase(Exception):
    """Base class for runtime failures. Carries no host detail to the caller."""


class RuntimeUnavailableError(RuntimeErrorBase):
    """The runtime backing this port cannot be reached.

    NEXUS must surface this. It must never degrade into host execution.
    """


class RuntimePolicyRejectedError(RuntimeErrorBase):
    """The runtime refused the policy, so isolation cannot be guaranteed."""


class RuntimeLimitExceededError(RuntimeErrorBase):
    """A resource limit or policy ceiling was hit."""


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    """Identity and shape of one sandbox, scoped to a single agent run."""

    name: str
    workspace_path: str
    image: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    cpu: str | None = None
    memory: str | None = None
    command: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("sandbox name must not be empty")
        if not self.workspace_path.strip():
            raise ValueError("sandbox workspace path must not be empty")


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    """Opaque reference to a created sandbox."""

    sandbox_id: str
    provider: RuntimeProvider
    name: str
    workspace_path: str


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    available: bool
    provider: RuntimeProvider
    detail: str = ""
    version: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    sandbox_id: str
    state: RuntimeState
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """One authorized unit of work inside a sandbox."""

    agent_run_id: EntityId
    tool_name: str
    command: tuple[str, ...]
    working_directory: str
    stdin: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    #: ``(host, port)`` destinations this command intends to contact.
    #:
    #: Declared up front rather than discovered afterwards so the runtime policy
    #: is consulted *before* the process starts. Adapters enforce the same set at
    #: the socket (OpenShell's policy proxy); this field is what lets the
    #: application layer refuse the call instead of merely observing it. An empty
    #: tuple means "no egress", which is the only safe reading under a DENY
    #: policy.
    network_endpoints: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    tool_name: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    truncated: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class TransferRequest:
    sandbox_id: str
    local_path: str
    remote_path: str | None = None


class AgentRuntimePort(ABC):
    """Provides a controlled, isolated environment to execute approved actions."""

    @property
    @abstractmethod
    def provider(self) -> RuntimeProvider:
        """Which isolation technology backs this adapter."""
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> RuntimeHealth:
        """Report reachability. Never falls back to another environment."""
        raise NotImplementedError

    @abstractmethod
    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        raise NotImplementedError

    @abstractmethod
    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        raise NotImplementedError

    @abstractmethod
    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        raise NotImplementedError

    @abstractmethod
    async def stop(self, handle: SandboxHandle) -> None:
        raise NotImplementedError

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        raise NotImplementedError

    async def upload(self, handle: SandboxHandle, request: TransferRequest) -> None:
        raise NotImplementedError

    async def download(self, handle: SandboxHandle, request: TransferRequest) -> None:
        raise NotImplementedError

    async def cleanup(self, handle: SandboxHandle) -> None:
        """Best-effort teardown. Never raises during error handling."""
        try:
            await self.destroy(handle)
        except Exception:  # noqa: BLE001 - teardown must not mask the original error
            return


def sandbox_labels(
    user_id: EntityId | None,
    agent_id: EntityId,
    agent_run_id: EntityId,
    session_id: EntityId | None = None,
) -> dict[str, str]:
    """Ownership labels applied to every sandbox so one run can never see another's."""
    labels = {
        "nexus.agent_id": str(agent_id),
        "nexus.agent_run_id": str(agent_run_id),
        "nexus.managed": "true",
    }
    if user_id is not None:
        labels["nexus.user_id"] = str(user_id)
    if session_id is not None:
        labels["nexus.runtime_session_id"] = str(session_id)
    return labels


def truncate_output(text: str, max_bytes: int) -> tuple[str, bool]:
    """Clamp captured output to a policy limit. Returns (text, was_truncated)."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    clamped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return clamped, True


__all__: Sequence[str] = (
    "AgentRuntimePort",
    "ExecutionRequest",
    "ExecutionResult",
    "RuntimeErrorBase",
    "RuntimeHealth",
    "RuntimeLimitExceededError",
    "RuntimePolicyRejectedError",
    "RuntimeStatus",
    "RuntimeUnavailableError",
    "SandboxHandle",
    "SandboxSpec",
    "TransferRequest",
    "sandbox_labels",
    "truncate_output",
)
