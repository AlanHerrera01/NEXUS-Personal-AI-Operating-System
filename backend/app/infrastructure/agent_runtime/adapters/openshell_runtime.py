"""``AgentRuntimePort`` implemented on the NVIDIA OpenShell CLI.

OpenShell is the isolation layer: it creates the sandbox, applies the policy and
executes inside it. NEXUS decides *whether* something may run; OpenShell decides
*where* and *under what limits*.

Every command below is built from the OpenShell CLI's own ``--help`` output at
runtime. The adapter never hardcodes an optional flag it has not confirmed the
installed CLI advertises, because OpenShell is pre-1.0 and its flags move
between releases. If a flag NEXUS needs is missing, the adapter refuses to run
rather than issuing a command the gateway would reject or, worse, interpret
differently than intended.

Documented surface used here (see https://docs.nvidia.com/openshell/home):

* ``openshell status``
* ``openshell sandbox create --name ... [--from ...] [--policy ...] [--cpu ...]
  [--memory ...] [--label k=v] [--detach] [--output json] -- <command>``
* ``openshell sandbox get <name> [--policy-only]``
* ``openshell sandbox exec -n <name> [--timeout s] -- <argv>``
* ``openshell sandbox stop <name>`` / ``openshell sandbox start <name>``
* ``openshell sandbox delete <name>``
* ``openshell policy set <name> --policy <file>``
* ``openshell sandbox --help`` (capability probe)

The policy document is written to a temporary file because ``--policy`` takes a
path, never inline YAML. No command is ever built as a string and no shell is
involved, so no tool argument can be reinterpreted.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

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
from app.infrastructure.agent_runtime.command_runner import CommandRunner, SubprocessCommandRunner
from app.infrastructure.agent_runtime.exceptions import (
    OpenShellCliError,
    OpenShellNotInstalledError,
)
from app.infrastructure.agent_runtime.policies.openshell_policy_renderer import (
    OpenShellPolicyRenderer,
)

logger = logging.getLogger(__name__)

CLI = "openshell"

#: Leaf subcommands whose documented flags the adapter depends on. Probing each
#: command separately rather than the whole group matters: `openshell sandbox
#: --help` lists options for every sandbox command at once, so a flag belonging
#: only to `create` would look available to `exec`.
PROBED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("status",),
    ("sandbox", "create"),
    ("sandbox", "exec"),
    ("sandbox", "get"),
    ("sandbox", "stop"),
    ("sandbox", "delete"),
    ("policy", "set"),
)

#: Phases reported by OpenShell mapped onto NEXUS runtime states.
_PHASE_STATES = {
    "provisioning": RuntimeState.INITIALIZING,
    "ready": RuntimeState.READY,
    "starting": RuntimeState.INITIALIZING,
    "stopping": RuntimeState.STOPPING,
    "stopped": RuntimeState.STOPPED,
    "completed": RuntimeState.STOPPED,
    "error": RuntimeState.FAILED,
    "deleting": RuntimeState.STOPPING,
}

_FLAG = re.compile(r"(?<![-\w])--[a-z0-9][a-z0-9-]*")

#: Condition reasons OpenShell raises when a sandbox will never converge.
_BLOCKING_REASONS = frozenset(
    {
        "ConfigurationInvalid",
        "ConfigurationIncomplete",
        "ProvisioningTimedOut",
        "ProvisioningFailed",
        "ImagePullFailed",
        "PolicyRejected",
    }
)


class OpenShellCapabilityError(RuntimeUnavailableError):
    """The installed CLI does not advertise a flag NEXUS requires."""


class OpenShellRuntimeAdapter(AgentRuntimePort):
    """Drives an OpenShell gateway as NEXUS's isolation layer."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        renderer: OpenShellPolicyRenderer | None = None,
        policy_directory: Path | None = None,
        command_timeout: float = 120.0,
    ) -> None:
        self.runner = runner or SubprocessCommandRunner(default_timeout=command_timeout)
        self.renderer = renderer or OpenShellPolicyRenderer()
        self.policy_directory = policy_directory
        self.command_timeout = command_timeout
        self._capabilities: dict[str, frozenset[str]] | None = None

    @property
    def provider(self) -> RuntimeProvider:
        return RuntimeProvider.OPENSHELL

    # -- capabilities ------------------------------------------------------

    async def capabilities(self) -> dict[str, frozenset[str]]:
        """Flags the installed CLI advertises, per leaf subcommand.

        Probed once and cached. This is what keeps the adapter honest across
        OpenShell versions: NEXUS emits only flags the local CLI actually
        documents, instead of flags that existed in some other release.
        """
        if self._capabilities is not None:
            return self._capabilities

        discovered: dict[str, frozenset[str]] = {}
        for subcommand in PROBED_COMMANDS:
            key = " ".join(subcommand)
            try:
                result = await self._run([CLI, *subcommand, "--help"], timeout=20.0)
            except Exception as error:  # noqa: BLE001 - a missing help page is not fatal
                logger.debug("could not read --help for %s: %s", key, error)
                discovered[key] = frozenset()
                continue
            text = f"{result.stdout}\n{result.stderr}"
            discovered[key] = frozenset(_FLAG.findall(text))

        self._capabilities = discovered
        return discovered

    def _supported(
        self, subcommand: str, flag: str, capabilities: dict[str, frozenset[str]]
    ) -> bool:
        """``--foo`` or a documented short form such as ``-n`` counts as supported."""
        flags = capabilities.get(subcommand, frozenset())
        if flag in flags:
            return True
        short = {"-n": "--name", "-o": "--output"}.get(flag)
        return bool(short and short in flags)

    def _require(
        self, subcommand: str, flag: str, capabilities: dict[str, frozenset[str]]
    ) -> None:
        if not self._supported(subcommand, flag, capabilities):
            raise OpenShellCapabilityError(
                f"the installed openshell CLI does not advertise {flag} for "
                f"`{subcommand}`; refusing to issue a command it may misinterpret"
            )

    # -- availability ------------------------------------------------------

    async def health(self) -> RuntimeHealth:
        if not self.runner.is_available(CLI):
            return RuntimeHealth(
                available=False,
                provider=RuntimeProvider.OPENSHELL,
                detail="the openshell CLI is not installed or not on PATH",
            )
        try:
            result = await self._run([CLI, "status"], timeout=15.0)
        except OpenShellNotInstalledError as error:
            return RuntimeHealth(False, RuntimeProvider.OPENSHELL, str(error))
        except OpenShellCliError as error:
            # `status` reports a reachable gateway with a non-zero code when it is
            # disconnected, which is a health answer, not a crash.
            return RuntimeHealth(
                False,
                RuntimeProvider.OPENSHELL,
                _sanitize(str(error)),
            )
        if not result.ok:
            return RuntimeHealth(
                False,
                RuntimeProvider.OPENSHELL,
                _sanitize(result.stderr or result.stdout) or "gateway is not reachable",
            )
        return RuntimeHealth(
            available=True,
            provider=RuntimeProvider.OPENSHELL,
            version=_read_version(result.stdout),
        )

    # -- lifecycle ---------------------------------------------------------

    async def create(self, spec: SandboxSpec, policy: RuntimePolicy) -> SandboxHandle:
        capabilities = await self.capabilities()
        policy_path = self._write_policy(spec.name, spec.workspace_path, policy)
        argv: list[str] = [CLI, "sandbox", "create", "--name", spec.name]
        if self._supported("sandbox create", "--policy", capabilities):
            argv += ["--policy", str(policy_path)]
        if self._supported("sandbox create", "--detach", capabilities):
            argv.append("--detach")
        if self._supported("sandbox create", "--output", capabilities):
            argv += ["--output", "json"]
        if spec.image and self._supported("sandbox create", "--from", capabilities):
            argv += ["--from", spec.image]
        if spec.cpu and self._supported("sandbox create", "--cpu", capabilities):
            argv += ["--cpu", spec.cpu]
        if spec.memory and self._supported("sandbox create", "--memory", capabilities):
            argv += ["--memory", spec.memory]
        if self._supported("sandbox create", "--label", capabilities):
            for key, value in sorted(spec.labels.items()):
                argv += ["--label", f"{key}={value}"]
        argv.append("--")
        argv += list(spec.command) or _idle_command()

        result = await self._run(argv)
        self._remove(policy_path)
        if not result.ok:
            raise RuntimeUnavailableError(
                _sanitize(result.stderr) or "sandbox creation was rejected by the gateway"
            )
        return SandboxHandle(
            sandbox_id=_read_sandbox_id(result.stdout) or spec.name,
            provider=self.provider,
            name=spec.name,
            workspace_path=spec.workspace_path,
        )

    async def apply_policy(self, handle: SandboxHandle, policy: RuntimePolicy) -> None:
        capabilities = await self.capabilities()
        policy_path = self._write_policy(handle.name, handle.workspace_path, policy)
        if not self._supported("policy set", "--policy", capabilities):
            self._remove(policy_path)
            raise OpenShellCapabilityError(
                "the installed openshell CLI cannot set a policy; isolation cannot be "
                "guaranteed so the sandbox will not be started"
            )
        result = await self._run(
            [CLI, "policy", "set", handle.name, "--policy", str(policy_path)],
            timeout=90.0,
        )
        self._remove(policy_path)
        if not result.ok:
            raise RuntimePolicyRejectedError(
                _sanitize(result.stderr or result.stdout) or "the runtime rejected the policy"
            )

    async def start(self, handle: SandboxHandle) -> SandboxHandle:
        result = await self._run([CLI, "sandbox", "start", handle.name], timeout=180.0)
        if not result.ok:
            raise RuntimeUnavailableError(
                _sanitize(result.stderr) or "sandbox could not be started"
            )
        return handle

    async def execute(
        self, handle: SandboxHandle, request: ExecutionRequest, policy: RuntimePolicy
    ) -> ExecutionResult:
        # Defence in depth: the service already validated this, the adapter does
        # not trust its caller. Egress is left to OpenShell's own policy proxy,
        # which is the component that actually sees the socket.
        if not policy.allows_path(request.working_directory):
            raise RuntimePolicyRejectedError("working directory is outside the workspace")

        capabilities = await self.capabilities()
        self._require("sandbox exec", "--name", capabilities)

        argv: list[str] = [CLI, "sandbox", "exec", "-n", handle.name]
        if self._supported("sandbox exec", "--timeout", capabilities):
            # OpenShell takes whole seconds; 0 would disable the limit entirely,
            # which is the opposite of what a bounded policy asks for.
            argv += ["--timeout", str(max(1, int(request.timeout_seconds)))]
        argv.append("--")
        argv += list(request.command)

        started = time.monotonic()
        result = await self._run(argv, timeout=request.timeout_seconds + 15.0)
        duration = time.monotonic() - started
        if result.timed_out:
            return ExecutionResult(
                tool_name=request.tool_name,
                exit_code=124,
                stdout=result.stdout,
                stderr="execution exceeded the policy timeout",
                duration_seconds=duration,
            )
        return ExecutionResult(
            tool_name=request.tool_name,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
        )

    async def status(self, handle: SandboxHandle) -> RuntimeStatus:
        capabilities = await self.capabilities()
        argv = [CLI, "sandbox", "get", handle.name]
        if self._supported("sandbox get", "--output", capabilities):
            argv += ["--output", "json"]
        result = await self._run(argv)
        if not result.ok:
            return RuntimeStatus(
                sandbox_id=handle.sandbox_id,
                state=RuntimeState.STOPPED,
                detail=_sanitize(result.stderr) or "sandbox not found",
            )
        payload = _read_json(result.stdout)
        return RuntimeStatus(
            sandbox_id=_read_sandbox_id(result.stdout) or handle.sandbox_id,
            state=_map_phase(payload),
            detail=str(payload.get("phase", "")),
            raw=payload if isinstance(payload, dict) else {},
        )

    async def stop(self, handle: SandboxHandle) -> None:
        result = await self._run([CLI, "sandbox", "stop", handle.name], timeout=120.0)
        if not result.ok:
            logger.warning("sandbox stop reported: %s", _sanitize(result.stderr))

    async def destroy(self, handle: SandboxHandle) -> None:
        result = await self._run([CLI, "sandbox", "delete", handle.name], timeout=120.0)
        if not result.ok:
            logger.warning("sandbox delete reported: %s", _sanitize(result.stderr))

    async def upload(self, handle: SandboxHandle, request: TransferRequest) -> None:
        """Copy a host file into the sandbox.

        ``openshell sandbox upload NAME LOCAL_PATH [DEST]``. The remote path is
        optional in the CLI, so it is omitted rather than guessed when the caller
        did not name one; inventing a destination inside a jail is how files end
        up somewhere the policy does not govern.

        The source must be a regular file. A directory, a symlink or a missing
        path is refused here rather than handed to the CLI, because the CLI would
        happily follow it and the request's ``local_path`` is caller-influenced.
        """
        source = Path(request.local_path)
        if not source.is_file():
            raise RuntimeUnavailableError(
                f"upload source is not a regular file: {source.name}"
            )

        argv = [CLI, "sandbox", "upload", handle.name, str(source)]
        if request.remote_path:
            argv.append(request.remote_path)

        result = await self._run(argv, timeout=self.command_timeout)
        if not result.ok:
            raise RuntimeUnavailableError(
                f"upload failed: {_sanitize(result.stderr or result.stdout)}"
            )

    async def download(self, handle: SandboxHandle, request: TransferRequest) -> None:
        """Copy a file out of the sandbox to the host.

        ``openshell sandbox download NAME SANDBOX_PATH [DEST]``. The destination
        defaults to the caller's ``local_path``. It is resolved to an absolute path
        before use so the write cannot land somewhere relative to an unexpected
        working directory, and it is created under a temporary name and moved into
        place only on success, so a failed transfer does not leave a truncated file
        that later looks like real output.
        """
        destination = Path(request.local_path)
        destination = destination.expanduser()
        if not destination.is_absolute():
            raise RuntimeUnavailableError(
                "download destination must be an absolute path"
            )

        remote = request.remote_path or "."
        staging = destination.with_name(f"{destination.name}.partial-{os.getpid()}")
        try:
            argv = [CLI, "sandbox", "download", handle.name, remote, str(staging)]
            result = await self._run(argv, timeout=self.command_timeout)
            if not result.ok:
                raise RuntimeUnavailableError(
                    f"download failed: {_sanitize(result.stderr or result.stdout)}"
                )
            if not staging.is_file():
                # The CLI reported success but wrote nothing. Moving a
                # non-existent file would raise a bare OSError that reads like a
                # bug in this adapter rather than a transfer that did not happen.
                raise RuntimeUnavailableError(
                    "download reported success but produced no file"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
        finally:
            # Best effort. A leftover ``.partial`` is inert; a partially written
            # file under the real name is not.
            try:
                staging.unlink(missing_ok=True)
            except OSError:  # noqa: BLE001 - cleanup is best effort
                logger.debug("could not remove staging file %s", staging)

    # -- internals ---------------------------------------------------------

    async def _run(self, argv: list[str], timeout: float | None = None, stdin: str | None = None):
        try:
            return await self.runner.run(
                argv, timeout=timeout or self.command_timeout, stdin=stdin
            )
        except OpenShellNotInstalledError as error:
            raise RuntimeUnavailableError(str(error)) from error

    def _write_policy(self, name: str, workspace_path: str, policy: RuntimePolicy) -> Path:
        directory = self.policy_directory or Path(tempfile.gettempdir()) / "nexus-openshell-policies"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}-policy.yaml"
        path.write_text(
            self.renderer.render_yaml(policy, workspace_path), encoding="utf-8"
        )
        return path

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:  # noqa: BLE001 - temp file cleanup is best effort
            logger.debug("could not remove policy file %s", path)


def _idle_command() -> list[str]:
    """Keeps a freshly created sandbox alive so it can be exec'd into later."""
    return ["/bin/sh", "-c", "sleep infinity"]


def _read_json(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            return {}
        try:
            payload = json.loads(text[start:])
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _read_sandbox_id(text: str) -> str | None:
    payload = _read_json(text)
    for key in ("id", "sandbox_id", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _read_version(text: str) -> str | None:
    payload = _read_json(text)
    for key in ("version", "gateway_version", "openshell_version"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _map_phase(payload: dict[str, Any]) -> RuntimeState:
    phase = str(payload.get("phase", "")).strip().lower()
    state = _PHASE_STATES.get(phase, RuntimeState.INITIALIZING)

    # A phase that has already settled is authoritative. Only while the sandbox
    # is still coming up does a settled blocking condition take precedence: a
    # configuration that will never converge must not be reported as merely
    # "provisioning" forever.
    if state in {RuntimeState.READY, RuntimeState.STOPPED, RuntimeState.FAILED}:
        return state

    for condition in _iter_conditions(payload):
        if _condition_reason(condition) in _BLOCKING_REASONS:
            return RuntimeState.BLOCKED
    return state


def _iter_conditions(payload: dict[str, Any]):
    conditions = payload.get("conditions")
    if not isinstance(conditions, list):
        return
    for condition in conditions:
        if isinstance(condition, str):
            yield condition
        elif isinstance(condition, dict):
            yield condition


def _condition_reason(condition: Any) -> str:
    if isinstance(condition, str):
        return condition.strip()
    if not isinstance(condition, dict):
        return ""
    status = condition.get("status", condition.get("satisfied"))
    # OpenShell reports condition status as a string in some builds and a bool
    # in others; anything other than a settled-true condition is not blocking.
    if isinstance(status, str) and status.strip().lower() not in {"true", "yes"}:
        return ""
    return str(condition.get("reason", condition.get("type", ""))).strip()


def _sanitize(text: str) -> str:
    """Keep gateway diagnostics useful without echoing credential-shaped values."""
    cleaned: list[str] = []
    for line in (text or "").splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in ("token", "secret", "password", "api_key", "apikey")):
            cleaned.append("<redacted credential-bearing line>")
            continue
        cleaned.append(line)
    joined = " ".join(cleaned).strip()
    return joined[:500]


__all__ = ["OpenShellCapabilityError", "OpenShellRuntimeAdapter"]
