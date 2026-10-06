"""In-memory ``AgentRuntimePort`` for tests.

Applies the same policy checks as the real adapters so a test that passes here
would pass against OpenShell, and can be told to fail so the "runtime down must
not fall back to the host" behaviour is testable without a broken gateway.
"""

from __future__ import annotations

from typing import Any, Callable

from app.domain.ports.agent_runtime import (
    AgentRuntimePort,
    ExecutionRequest,
    ExecutionResult,
    RuntimeHealth,
    RuntimePolicyRejectedError,
    RuntimeStatus,
    RuntimeUnavailableError,
    SandboxHandle,
    SandboxSpec,
    TransferRequest,
)
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState


class FakeAgentRuntime(AgentRuntimePort):
    """Records every call so tests can assert on the lifecycle, not just the result."""

    def __init__(
        self,
        available: bool = True,
        result: ExecutionResult | None = None,
        execute_hook: Callable[[SandboxHandle, ExecutionRequest], ExecutionResult] | None = None,
    ) -> None:
        self.available = available
        self.result = result
        self.execute_hook = execute_hook
        self.calls: list[tuple[str, Any]] = []
        self.sandboxes: dict[str, SandboxHandle] = {}

    @property
    def provider(self) -> RuntimeProvider:
        return RuntimeProvider.IN_MEMORY

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    async def health(self) -> RuntimeHealth:
        self.calls.append(("health", None))
        if not self.available:
            return RuntimeHealth(False, self.provider, "runtime is disabled")
        return RuntimeHealth(True, self.provider, "fake runtime")

    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        self.calls.append(("create", spec))
        if not self.available:
            raise RuntimeUnavailableError("runtime is disabled")
        handle = SandboxHandle(
            sandbox_id=f"fake-{spec.name}",
            provider=self.provider,
            name=spec.name,
            workspace_path=spec.workspace_path,
        )
        self.sandboxes[handle.sandbox_id] = handle
        return handle

    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        self.calls.append(("apply_policy", policy))
        if not policy.is_isolation_intact():
            raise RuntimePolicyRejectedError("policy would not preserve isolation")

    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        self.calls.append(("start", handle))
        return handle

    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        self.calls.append(("execute", request))
        if not self.available:
            raise RuntimeUnavailableError("runtime is disabled")
        if not policy.allows_path(request.working_directory):
            raise RuntimePolicyRejectedError("working directory is outside the workspace")
        if self.execute_hook is not None:
            return self.execute_hook(handle, request)
        if self.result is not None:
            return self.result
        return ExecutionResult(
            tool_name=request.tool_name,
            exit_code=0,
            stdout="",
            stderr="",
            duration_seconds=0.0,
        )

    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        self.calls.append(("status", handle))
        return RuntimeStatus(handle.sandbox_id, RuntimeState.READY, "fake")

    async def stop(self, handle: SandboxHandle) -> None:
        self.calls.append(("stop", handle))

    async def destroy(self, handle: SandboxHandle) -> None:
        self.calls.append(("destroy", handle))
        self.sandboxes.pop(handle.sandbox_id, None)

    async def upload(self, handle: SandboxHandle, request: TransferRequest) -> None:
        self.calls.append(("upload", request))

    async def download(self, handle: SandboxHandle, request: TransferRequest) -> None:
        self.calls.append(("download", request))
