"""Builds the runtime policy for an action.

Deny by default. Every capability is opt-in and every limit comes from
configuration, never from a hardcoded constant chosen at the call site. The
factory can only narrow what the system-wide baseline allows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.agent_runtime.settings import RuntimeLimitsConfig
from app.domain.ports.tool import ToolDefinition
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

#: Read-only system paths. Matches the baseline an OpenShell sandbox already
#: needs to run; nothing outside this list and the workspace is readable.
DEFAULT_READ_ONLY_PATHS: tuple[str, ...] = ("/usr", "/lib", "/etc", "/dev/urandom")

#: Egress needed for the sandbox to reach NEXUS's own inference provider.
DEFAULT_ALLOWED_ENDPOINTS: tuple[NetworkEndpoint, ...] = (
    NetworkEndpoint(host="api.studio.nebius.ai", port=443, protocol="rest", access="read-write"),
)


@dataclass(frozen=True, slots=True)
class RuntimeBaseline:
    """The widest policy the deployment permits. Per-action policies narrow this."""

    filesystem: FilesystemPolicy
    network: NetworkPolicy
    processes: ProcessPolicy
    resources: ResourceLimits
    credentials: CredentialPolicy
    expiration_seconds: int

    @classmethod
    def from_config(cls, config: RuntimeLimitsConfig) -> "RuntimeBaseline":
        endpoints = tuple(
            NetworkEndpoint(host=host, port=port, protocol="rest", access=access)
            for host, port, access in config.allowed_network_endpoints
        )
        return cls(
            filesystem=FilesystemPolicy(
                workspace_only=True,
                read_only_paths=tuple(config.read_only_paths or DEFAULT_READ_ONLY_PATHS),
                read_write_paths=(),
            ),
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED if endpoints else NetworkMode.DENY,
                allowed_endpoints=endpoints,
            ),
            processes=ProcessPolicy(
                max_processes=config.max_processes,
                allowed_binaries=tuple(config.allowed_binaries),
            ),
            resources=ResourceLimits(
                max_execution_seconds=config.max_execution_seconds,
                max_output_bytes=config.max_output_bytes,
                max_memory_mb=config.max_memory_mb,
                max_cpu=config.max_cpu,
                max_filesystem_bytes=config.max_filesystem_bytes,
                max_network_requests=config.max_network_requests,
                max_tool_calls=config.max_tool_calls,
            ),
            credentials=CredentialPolicy(
                allow_host_access=False,
                allow_runtime_injection=False,
            ),
            expiration_seconds=config.expiration_seconds,
        )

    def to_policy(self) -> RuntimePolicy:
        return RuntimePolicy(
            filesystem=self.filesystem,
            network=self.network,
            processes=self.processes,
            resources=self.resources,
            credentials=self.credentials,
            expiration_seconds=self.expiration_seconds,
        )


class RuntimePolicyFactory:
    """Derives the policy for one tool call from the baseline and the tool itself."""

    def __init__(self, baseline: RuntimeBaseline) -> None:
        self.baseline = baseline

    @property
    def policy(self) -> RuntimePolicy:
        return self.baseline.to_policy()

    def for_tool(
        self,
        tool: ToolDefinition | None,
        requested_endpoints: tuple[NetworkEndpoint, ...] = (),
        needs_network: bool = False,
        timeout_seconds: float | None = None,
    ) -> RuntimePolicy:
        policy = self.baseline.to_policy()

        if not needs_network:
            policy = replace(policy, network=NetworkPolicy(mode=NetworkMode.DENY))
        elif requested_endpoints:
            permitted = tuple(
                endpoint
                for endpoint in requested_endpoints
                if endpoint in self.baseline.network.allowed_endpoints
            )
            policy = policy.with_endpoints(permitted)

        if tool is not None:
            policy = replace(policy, allowed_tool_names=frozenset({tool.name}))
            if timeout_seconds is not None and timeout_seconds > 0:
                policy = replace(
                    policy,
                    resources=replace(
                        policy.resources,
                        max_execution_seconds=min(
                            timeout_seconds, policy.resources.max_execution_seconds
                        ),
                    ),
                )
            # A high-risk tool never gets more room than a low-risk one.
            if tool.risk_level.value == "HIGH":
                policy = replace(
                    policy,
                    resources=replace(
                        policy.resources,
                        max_tool_calls=1,
                        max_network_requests=0,
                    ),
                )
        return policy
