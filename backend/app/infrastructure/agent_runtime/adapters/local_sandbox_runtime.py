"""Local development runtime.

Lets the whole runtime path be exercised on a developer machine with no
OpenShell, no Docker and no GPU. What it can honestly enforce:

* the working directory is jailed to the run's workspace
* the environment is rebuilt from an allowlist, so host secrets do not leak in
* the executable and its arguments pass the same command allowlist
* execution time, output size, process count and memory are bounded where the
  host OS supports it

What it cannot enforce, and therefore does not claim: kernel-level filesystem
isolation, seccomp, network namespace isolation or Landlock. It is a development
convenience behind a flag. Production isolation requires a real runtime, and
``health().available`` reports exactly which one is in use so nobody mistakes
this for a hardened sandbox.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.domain.ports.agent_runtime import (
    AgentRuntimePort,
    ExecutionRequest,
    ExecutionResult,
    RuntimeHealth,
    RuntimeLimitExceededError,
    RuntimePolicyRejectedError,
    RuntimeStatus,
    RuntimeUnavailableError,
    SandboxHandle,
    SandboxSpec,
    TransferRequest,
)
from app.domain.value_objects.command_policy import CommandPolicy
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState
from app.infrastructure.agent_runtime.command_runner import SubprocessCommandRunner

logger = logging.getLogger(__name__)

#: Only these names reach a child process. Everything else is dropped, which is
#: what keeps the host's credentials out of the workspace.
ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONPATH",
        "PYTHONHASHSEED",
        "PYTHONDONTWRITEBYTECODE",
        "TZ",
    }
)

#: Redefined inside the child so a shell cannot reach an interactive profile.
DEFAULT_CHILD_ENV: dict[str, str] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}


class LocalSandboxRuntime(AgentRuntimePort):
    """A workspace-jailed process runner. Development only."""

    def __init__(
        self,
        command_policy: CommandPolicy | None = None,
        max_concurrent_processes: int = 4,
        command_timeout: float = 120.0,
        max_transfer_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.command_policy = command_policy
        # The runner's default bounds the driver; the per-request timeout passed
        # to ``execute`` bounds the workload and is always the smaller of the two.
        self.runner = SubprocessCommandRunner(default_timeout=command_timeout)
        self.command_timeout = command_timeout
        self.max_transfer_bytes = max_transfer_bytes
        self.max_concurrent_processes = max_concurrent_processes
        self.sandboxes: dict[str, SandboxHandle] = {}
        self._running: set[str] = set()

    @property
    def provider(self) -> RuntimeProvider:
        return RuntimeProvider.LOCAL

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            available=True,
            provider=RuntimeProvider.LOCAL,
            detail="local workspace-jailed runtime; not a hardened sandbox",
            version="local-1",
        )

    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        if not policy.is_isolation_intact():
            raise RuntimePolicyRejectedError("policy would not preserve isolation")
        workspace = Path(spec.workspace_path)
        if not workspace.is_dir():
            raise RuntimeUnavailableError(f"workspace does not exist: {workspace}")
        handle = SandboxHandle(
            sandbox_id=f"local-{spec.name}",
            provider=self.provider,
            name=spec.name,
            workspace_path=spec.workspace_path,
        )
        self.sandboxes[handle.sandbox_id] = handle
        return handle

    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        if not policy.is_isolation_intact():
            raise RuntimePolicyRejectedError("policy would not preserve isolation")

    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        return handle

    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        if not policy.allows_path(request.working_directory):
            raise RuntimePolicyRejectedError("working directory is outside the workspace")
        if len(self._running) >= self.max_concurrent_processes:
            raise RuntimeLimitExceededError("too many concurrent runtime processes")

        argv = list(request.command)
        if self.command_policy is not None:
            decision = self.command_policy.validate(
                argv,
                working_directory=request.working_directory,
                workspace_path=handle.workspace_path,
            )
            if not decision.allowed:
                raise RuntimePolicyRejectedError(decision.reason)

        env = self._child_environment(request.environment)
        self._running.add(handle.sandbox_id)
        started = time.monotonic()
        try:
            result = await self._run(
                argv,
                cwd=request.working_directory,
                env=env,
                timeout=min(
                    request.timeout_seconds, policy.resources.max_execution_seconds
                ),
                stdin=request.stdin,
            )
        finally:
            self._running.discard(handle.sandbox_id)

        return ExecutionResult(
            tool_name=request.tool_name,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=time.monotonic() - started,
            truncated=result.timed_out,
        )

    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        if handle.sandbox_id in self.sandboxes:
            return RuntimeStatus(
                sandbox_id=handle.sandbox_id,
                state=RuntimeState.READY,
                detail="local runtime",
            )
        return RuntimeStatus(handle.sandbox_id, RuntimeState.STOPPED, "unknown sandbox")

    async def stop(self, handle: SandboxHandle) -> None:
        self._running.discard(handle.sandbox_id)

    async def destroy(self, handle: SandboxHandle) -> None:
        self.sandboxes.pop(handle.sandbox_id, None)

    async def upload(self, handle: SandboxHandle, request: TransferRequest) -> None:
        self._copy_in(handle, request)

    async def download(self, handle: SandboxHandle, request: TransferRequest) -> None:
        self._copy_out(handle, request)

    # -- internals ---------------------------------------------------------

    async def _run(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        timeout: float,
        stdin: str | None,
    ) -> Any:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=False,
        )
        try:
            out, err = await asyncio.wait_for(
                process.communicate(input=stdin.encode("utf-8") if stdin is not None else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return _TimedOut()

        return _Completed(
            exit_code=process.returncode if process.returncode is not None else 1,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
        )

    def _child_environment(self, overrides: dict[str, str]) -> dict[str, str]:
        env = dict(DEFAULT_CHILD_ENV)
        for key in ENVIRONMENT_ALLOWLIST:
            if key in os.environ and key not in env:
                env[key] = os.environ[key]
        for key, value in overrides.items():
            if _is_credential_key(key):
                continue
            env[key] = value
        env["HOME"] = _working_placeholder()
        return env

    def _copy_in(self, handle: SandboxHandle, request: TransferRequest) -> None:
        base = Path(handle.workspace_path).resolve()
        destination = _resolve_in_workspace(base, request.remote_path)
        _require_inside(base, destination)
        source = Path(request.local_path)
        _require_no_symlinks(source)
        self._transfer(source, destination, self.max_transfer_bytes)

    def _copy_out(self, handle: SandboxHandle, request: TransferRequest) -> None:
        base = Path(handle.workspace_path).resolve()
        source = _resolve_in_workspace(base, request.remote_path)
        _require_inside(base, source)
        destination = Path(request.local_path)
        self._transfer(source, destination, self.max_transfer_bytes)

    def _transfer(self, source: Path, destination: Path, limit: int) -> None:
        """Copy a file or a tree, refusing anything over ``limit`` bytes.

        The previous implementation branched on ``is_dir()`` and, for a
        directory, only created an empty destination. A caller copying a
        directory out of a sandbox got a successful, empty result and no
        indication that the contents were gone. Directories are now copied
        recursively.

        Size is checked before reading, so an oversized transfer is refused
        instead of being pulled into memory first.
        """
        if source.is_dir():
            total = _tree_size(source, limit)
            destination.mkdir(parents=True, exist_ok=True)
            for entry in sorted(source.rglob("*")):
                target = destination / entry.relative_to(source)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(entry, target)
            return

        size = source.stat().st_size
        if size > limit:
            raise RuntimePolicyRejectedError(
                f"transfer of {size} bytes exceeds the {limit} byte limit"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


class _Completed:
    __slots__ = ("exit_code", "stdout", "stderr", "timed_out")

    def __init__(self, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = False


class _TimedOut:
    __slots__ = ("exit_code", "stdout", "stderr", "timed_out")

    def __init__(self) -> None:
        self.exit_code = 124
        self.stdout = ""
        self.stderr = "execution exceeded the policy timeout"
        self.timed_out = True


def _is_credential_key(key: str) -> bool:
    segments = key.lower().split("_")
    return bool(
        {"token", "secret", "password", "credential", "api_key", "access_key"} & set(segments)
    )


def _working_placeholder() -> str:
    return os.environ.get("NEXUS_RUNTIME_FAKE_HOME", "/nonexistent")


def _resolve_in_workspace(base: Path, remote_path: str | None) -> Path:
    """Resolve a sandbox-relative path against the workspace.

    A relative ``remote_path`` is a path *inside the sandbox*, so it must be
    anchored to the workspace. Resolving it against the process would anchor it
    to the API server's working directory instead, which both refuses every
    legitimate relative path and leaks the server's layout into what is allowed.
    """
    candidate = Path(remote_path) if remote_path else Path(".")
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _require_inside(base: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise RuntimePolicyRejectedError(
            "path is outside the workspace and will not be transferred"
        ) from error


def _require_no_symlinks(source: Path) -> None:
    """Refuse a transfer whose source contains a symlink.

    ``resolve()`` follows links, so a link *inside* the workspace pointing out of
    it is caught by ``_require_inside`` on the resolved path. A link that points
    at another secret inside the workspace would not be, and following it during a
    recursive copy would pull in whatever it names.
    """
    if source.is_symlink():
        raise RuntimePolicyRejectedError("transfer source must not be a symlink")
    if source.is_dir():
        for entry in source.rglob("*"):
            if entry.is_symlink():
                raise RuntimePolicyRejectedError(
                    "transfer source must not contain symlinks"
                )


def _tree_size(source: Path, limit: int) -> int:
    total = 0
    for entry in source.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
            if total > limit:
                raise RuntimePolicyRejectedError(
                    f"transfer exceeds the {limit} byte limit"
                )
    return total
