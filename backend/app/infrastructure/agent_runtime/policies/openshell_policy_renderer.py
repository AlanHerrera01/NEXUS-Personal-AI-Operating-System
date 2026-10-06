"""Renders a NEXUS ``RuntimePolicy`` as an OpenShell sandbox policy document.

The output conforms to the documented OpenShell policy schema (version 1):
``filesystem_policy`` with ``include_workdir``/``read_only``/``read_write``,
``landlock``, ``process``, and ``network_policies`` mapping a rule name to
``endpoints`` and ``binaries``. Enforcement is always ``enforce``: ``audit``
would log a denied request and allow it, which is the opposite of what NEXUS
means by a block.
"""

from __future__ import annotations

from typing import Any

import yaml

from app.domain.value_objects.network_mode import NetworkMode
from app.domain.value_objects.runtime_policy import RuntimePolicy

#: A policy may not list more paths than the schema accepts.
MAX_POLICY_PATHS = 256


class OpenShellPolicyRenderer:
    """Pure translation. No I/O, no CLI, no knowledge of NEXUS services."""

    def __init__(self, rule_prefix: str = "nexus") -> None:
        self.rule_prefix = rule_prefix

    def render(self, policy: RuntimePolicy, workspace_path: str) -> dict[str, Any]:
        read_write = [_posix(path) for path in policy.filesystem.effective_read_write]
        read_only = [
            _posix(path) for path in policy.filesystem.read_only_paths if path not in read_write
        ]
        if len(read_only) + len(read_write) > MAX_POLICY_PATHS:
            raise ValueError("policy exceeds the maximum number of filesystem paths")

        document: dict[str, Any] = {
            "version": 1,
            "filesystem_policy": {
                "include_workdir": bool(workspace_path),
                "read_only": sorted(read_only),
                "read_write": sorted(read_write),
            },
            "landlock": {"compatibility": "hard_requirement"},
            "process": {
                "run_as_user": policy.processes.run_as_user,
                "run_as_group": policy.processes.run_as_group,
            },
        }

        rules = self._network_rules(policy)
        if rules:
            document["network_policies"] = rules
        return document

    def render_yaml(self, policy: RuntimePolicy, workspace_path: str) -> str:
        return yaml.safe_dump(
            self.render(policy, workspace_path),
            sort_keys=False,
            default_flow_style=False,
        )

    def _network_rules(self, policy: RuntimePolicy) -> dict[str, Any]:
        if policy.network.mode is NetworkMode.DENY or not policy.network.allowed_endpoints:
            return {}

        endpoints: list[dict[str, Any]] = []
        for endpoint in policy.network.allowed_endpoints:
            rendered: dict[str, Any] = {
                "host": endpoint.host,
                "port": endpoint.port,
                "enforcement": "enforce",
            }
            if endpoint.protocol == "tcp":
                # `protocol: tcp` is L4 only and accepts no request-level rules.
                rendered["protocol"] = "tcp"
            else:
                # Naming a protocol is what turns on L7 inspection. Leaving it
                # off would silently downgrade the rule to a bare host/port
                # allow, so it is always emitted.
                rendered["protocol"] = endpoint.protocol
                if endpoint.path:
                    rendered["rules"] = [
                        {"allow": {"method": _method(endpoint.access), "path": endpoint.path}}
                    ]
            endpoints.append(rendered)

        binaries = [
            {"path": binary}
            for binary in policy.processes.allowed_binaries
            or policy.network.allowed_binaries
        ]
        return {
            f"{self.rule_prefix}_egress": {
                "name": f"{self.rule_prefix}-approved-egress",
                "endpoints": endpoints,
                "binaries": binaries,
            }
        }


def _posix(path: str) -> str:
    """Render a path with forward slashes.

    OpenShell runs Linux sandboxes even when NEXUS is configured from Windows,
    so a Windows-style separator in a policy path would be silently ineffective.
    """
    return path.replace("\\", "/")


def _method(access: str) -> str:
    """The narrowest HTTP method consistent with the requested access level.

    A read-only endpoint is granted GET rather than a wildcard, so a bug or a
    compromised binary cannot turn a read grant into a write.
    """
    if access == "read-only":
        return "GET"
    if access == "read-write":
        return "POST"
    return "*"
