"""Runtime policy: the answer to "under which restrictions may this run?".

Distinct from ``TrustPolicy``, which answers "is this action allowed at all?".
A TrustPolicy ALLOW says nothing about the filesystem, network, processes or
resource ceiling the action will actually get. That is this object's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.domain.value_objects.network_mode import NetworkMode
from app.domain.value_objects.path_guard import canonicalise, contains

#: Never mount these into a sandbox, whatever a caller asks for.
FORBIDDEN_HOST_PATHS: tuple[str, ...] = (
    "/",
    "/root",
    "/home",
    "/proc/1",
    "/etc/shadow",
)

#: Loopback, link-local and cloud metadata. Matches the ranges OpenShell also blocks.
BLOCKED_NETWORK_HOSTS: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",
    "metadata.google.internal",
)


class PolicyViolation(ValueError):
    """Raised when a runtime policy is structurally impossible or unsafe."""


@dataclass(frozen=True, slots=True)
class NetworkEndpoint:
    """One explicitly permitted egress destination."""

    host: str
    port: int = 443
    #: rest | websocket | graphql | mcp | json-rpc | tcp, as understood by the renderer.
    protocol: str = "rest"
    #: read-only | read-write | full
    access: str = "read-only"
    path: str | None = None

    def __post_init__(self) -> None:
        if not self.host or not self.host.strip():
            raise PolicyViolation("network endpoint host must not be empty")
        if self.host.lower() in BLOCKED_NETWORK_HOSTS:
            raise PolicyViolation(f"endpoint host is never reachable from a runtime: {self.host}")
        if not 1 <= self.port <= 65535:
            raise PolicyViolation(f"endpoint port out of range: {self.port}")
        if self.access not in {"read-only", "read-write", "full"}:
            raise PolicyViolation(f"unsupported endpoint access preset: {self.access}")


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    """What the workload may read and write. Workspace-only unless widened on purpose."""

    workspace_only: bool = True
    workspace_path: str = ""
    read_only_paths: tuple[str, ...] = ("/usr", "/lib", "/etc", "/dev/urandom")
    read_write_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for path in (*self.read_only_paths, *self.read_write_paths):
            if path in FORBIDDEN_HOST_PATHS:
                raise PolicyViolation(f"host path may never be exposed to a runtime: {path}")
            if ".." in path:
                raise PolicyViolation(f"path traversal is not allowed in a policy: {path}")
        if not self.workspace_only and self.workspace_path not in self.read_write_paths:
            raise PolicyViolation("writable paths must include the workspace when it is writable")

    @property
    def effective_read_write(self) -> tuple[str, ...]:
        paths = list(self.read_write_paths)
        if self.workspace_only and self.workspace_path and self.workspace_path not in paths:
            paths.append(self.workspace_path)
        return tuple(paths)


@dataclass(frozen=True, slots=True)
class ProcessPolicy:
    """Process-level restrictions. No privilege escalation, bounded fan-out."""

    max_processes: int = 64
    run_as_user: str = "sandbox"
    run_as_group: str = "sandbox"
    no_new_privileges: bool = True
    #: Binaries the workload may execute at all.
    allowed_binaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_processes < 1:
            raise PolicyViolation("max_processes must be at least 1")
        for identity in (self.run_as_user, self.run_as_group):
            if identity.strip().isdigit() and int(identity) == 0:
                raise PolicyViolation("a runtime must not run as root")

    @property
    def is_execution_restricted(self) -> bool:
        return bool(self.allowed_binaries)


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Abuse ceilings. Every field is configurable; none are hardcoded per call."""

    max_execution_seconds: float = 30.0
    max_output_bytes: int = 262_144
    max_memory_mb: int = 512
    max_cpu: str = "1"
    max_filesystem_bytes: int = 67_108_864
    max_network_requests: int = 16
    max_tool_calls: int = 10

    def __post_init__(self) -> None:
        if self.max_execution_seconds <= 0:
            raise PolicyViolation("max_execution_seconds must be positive")
        if self.max_output_bytes < 1:
            raise PolicyViolation("max_output_bytes must be positive")
        if self.max_memory_mb < 32:
            raise PolicyViolation("max_memory_mb below 32Mi is not a usable floor")
        if self.max_network_requests < 0:
            raise PolicyViolation("max_network_requests cannot be negative")
        if self.max_tool_calls < 0:
            raise PolicyViolation("max_tool_calls cannot be negative")


@dataclass(frozen=True, slots=True)
class CredentialPolicy:
    """Credential exposure rules.

    ``allow_host_access`` is the switch that keeps secrets out of the model: when
    False, the runtime receives resolver placeholders and the real value never
    crosses into sandbox-visible state.
    """

    allow_host_access: bool = False
    allowed_credential_names: frozenset[str] = frozenset()
    allow_runtime_injection: bool = False

    @property
    def exposes_secrets_to_runtime(self) -> bool:
        return self.allow_host_access or self.allow_runtime_injection


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Egress posture. DENY by default; RESTRICTED means allowlist-only."""

    mode: NetworkMode = NetworkMode.DENY
    allowed_endpoints: tuple[NetworkEndpoint, ...] = ()
    #: Binaries permitted to originate a connection.
    allowed_binaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Coerce before validating. A mode that arrived from a database row, a
        # JSON payload or an env var is a plain ``str``, and every check below
        # compares by identity (``is not NetworkMode.ALLOW``). A raw "ALLOW"
        # string is *not* the enum member, so an uncoerced value would slip past
        # this guard and past ``is_isolation_intact`` - a fail-open bug on
        # exactly the setting that decides whether egress is unrestricted.
        mode = self.mode if isinstance(self.mode, NetworkMode) else NetworkMode(str(self.mode).upper())
        object.__setattr__(self, "mode", mode)
        if mode is NetworkMode.DENY and self.allowed_endpoints:
            raise PolicyViolation("network mode DENY cannot carry allowed endpoints")
        if mode is NetworkMode.ALLOW:
            raise PolicyViolation(
                "network mode ALLOW is never permitted: runtime egress is allowlist-only"
            )

    @property
    def is_restricted(self) -> bool:
        return self.mode is NetworkMode.RESTRICTED


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """The complete set of restrictions applied to one runtime session."""

    filesystem: FilesystemPolicy = field(default_factory=FilesystemPolicy)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    processes: ProcessPolicy = field(default_factory=ProcessPolicy)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    credentials: CredentialPolicy = field(default_factory=CredentialPolicy)
    expiration_seconds: int = 900
    allowed_tool_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.expiration_seconds < 1:
            raise PolicyViolation("expiration_seconds must be positive")
        if self.network.mode is NetworkMode.DENY and self.network.allowed_endpoints:
            raise PolicyViolation("network mode DENY cannot carry allowed endpoints")
        if self.network.mode is NetworkMode.ALLOW:
            raise PolicyViolation(
                "network mode ALLOW is never permitted: runtime egress is allowlist-only"
            )

    # -- combination -------------------------------------------------------

    def restrict_to(self, other: "RuntimePolicy") -> "RuntimePolicy":
        """Return the most restrictive of two policies. Never widens a limit."""
        return RuntimePolicy(
            filesystem=FilesystemPolicy(
                workspace_only=self.filesystem.workspace_only and other.filesystem.workspace_only,
                workspace_path=self.filesystem.workspace_path or other.filesystem.workspace_path,
                read_only_paths=self.filesystem.read_only_paths,
                read_write_paths=self.filesystem.effective_read_write,
            ),
            network=NetworkPolicy(
                mode=(
                    NetworkMode.DENY
                    if NetworkMode.DENY in {self.network.mode, other.network.mode}
                    else NetworkMode.RESTRICTED
                ),
                allowed_endpoints=tuple(
                    endpoint
                    for endpoint in self.network.allowed_endpoints
                    if endpoint in other.network.allowed_endpoints
                ),
                allowed_binaries=self.network.allowed_binaries,
            ),
            processes=ProcessPolicy(
                max_processes=min(self.processes.max_processes, other.processes.max_processes),
                run_as_user=self.processes.run_as_user,
                run_as_group=self.processes.run_as_group,
                no_new_privileges=True,
                allowed_binaries=self.processes.allowed_binaries or other.processes.allowed_binaries,
            ),
            resources=ResourceLimits(
                max_execution_seconds=min(
                    self.resources.max_execution_seconds, other.resources.max_execution_seconds
                ),
                max_output_bytes=min(
                    self.resources.max_output_bytes, other.resources.max_output_bytes
                ),
                max_memory_mb=min(self.resources.max_memory_mb, other.resources.max_memory_mb),
                max_cpu=self.resources.max_cpu,
                max_filesystem_bytes=min(
                    self.resources.max_filesystem_bytes, other.resources.max_filesystem_bytes
                ),
                max_network_requests=min(
                    self.resources.max_network_requests, other.resources.max_network_requests
                ),
                max_tool_calls=min(self.resources.max_tool_calls, other.resources.max_tool_calls),
            ),
            credentials=CredentialPolicy(
                allow_host_access=False,
                allowed_credential_names=self.credentials.allowed_credential_names
                & other.credentials.allowed_credential_names,
                allow_runtime_injection=False,
            ),
            expiration_seconds=min(self.expiration_seconds, other.expiration_seconds),
            allowed_tool_names=self.allowed_tool_names & other.allowed_tool_names,
        )

    # -- checks ------------------------------------------------------------

    def with_workspace(self, workspace_path: str) -> "RuntimePolicy":
        return replace(
            self,
            filesystem=replace(
                self.filesystem, workspace_path=workspace_path, workspace_only=True
            ),
        )

    def with_endpoints(self, endpoints: tuple[NetworkEndpoint, ...]) -> "RuntimePolicy":
        return replace(
            self,
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED if endpoints else NetworkMode.DENY,
                allowed_endpoints=endpoints,
                allowed_binaries=self.network.allowed_binaries,
            ),
        )

    def allows_endpoint(self, host: str, port: int) -> bool:
        if self.network.mode is NetworkMode.DENY:
            return False
        return any(
            endpoint.host == host and endpoint.port == port
            for endpoint in self.network.allowed_endpoints
        )

    def allows_path(self, path: str) -> bool:
        """True when a path falls inside an explicitly permitted location.

        The path is canonicalised before containment is tested, so
        ``<workspace>/../../etc`` cannot prefix-match the workspace. Both sides
        are compared in the same normalised form: a workspace configured with
        Windows separators must still match a request that uses forward
        slashes, or every legitimate call would be denied on that platform.
        """
        normalised = canonicalise(path)
        if normalised.startswith("~") or "/.ssh" in normalised or "/.aws" in normalised:
            return False
        return any(
            contains(writable, normalised)
            for writable in self.filesystem.effective_read_write
        )

    def allows_binary(self, binary: str) -> bool:
        if not self.processes.is_execution_restricted:
            return True
        return binary in self.processes.allowed_binaries

    def is_isolation_intact(self) -> bool:
        """The invariants that must hold before any execution is allowed."""
        return (
            self.filesystem.workspace_only
            and self.network.mode is not NetworkMode.ALLOW
            and not self.credentials.exposes_secrets_to_runtime
            and self.processes.no_new_privileges
        )

    def describe(self) -> dict[str, Any]:
        """Redacted summary. Contains no credentials and no host paths."""
        return {
            "filesystem": {
                "workspace_only": self.filesystem.workspace_only,
                "read_only": list(self.filesystem.read_only_paths),
                "read_write": list(self.filesystem.effective_read_write),
            },
            "network": {
                "mode": self.network.mode.value,
                "allowed_endpoints": [
                    f"{e.host}:{e.port}" for e in self.network.allowed_endpoints
                ],
            },
            "processes": {
                "max_processes": self.processes.max_processes,
                "no_new_privileges": self.processes.no_new_privileges,
                "allowed_binaries": list(self.processes.allowed_binaries),
            },
            "resources": {
                "max_execution_seconds": self.resources.max_execution_seconds,
                "max_output_bytes": self.resources.max_output_bytes,
                "max_memory_mb": self.resources.max_memory_mb,
                "max_cpu": self.resources.max_cpu,
                "max_filesystem_bytes": self.resources.max_filesystem_bytes,
                "max_network_requests": self.resources.max_network_requests,
                "max_tool_calls": self.resources.max_tool_calls,
            },
            "credentials": {
                "allow_host_access": self.credentials.allow_host_access,
                "allow_runtime_injection": self.credentials.allow_runtime_injection,
            },
            "expiration_seconds": self.expiration_seconds,
        }
