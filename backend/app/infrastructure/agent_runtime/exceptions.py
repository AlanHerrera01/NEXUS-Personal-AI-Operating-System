"""Runtime adapter failures.

The OpenShell adapter wraps the ``openshell`` CLI. Every command it issues is one
that appears in the official CLI reference; nothing here invents a flag. When
the CLI, the gateway or the compute driver is missing, the adapter raises
``RuntimeUnavailableError`` and NEXUS surfaces it. It never degrades to running
the same command on the host.
"""

from app.domain.ports.agent_runtime import (
    RuntimeErrorBase,
    RuntimeLimitExceededError,
    RuntimePolicyRejectedError,
    RuntimeUnavailableError,
)

__all__ = [
    "OpenShellCliError",
    "OpenShellNotInstalledError",
    "RuntimeErrorBase",
    "RuntimeLimitExceededError",
    "RuntimePolicyRejectedError",
    "RuntimeUnavailableError",
]


class OpenShellCliError(RuntimeErrorBase):
    """The ``openshell`` CLI returned a non-zero exit code."""


class OpenShellNotInstalledError(OpenShellCliError):
    """The ``openshell`` binary is not on PATH."""
