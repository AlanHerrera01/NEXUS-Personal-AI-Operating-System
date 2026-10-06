"""Credential custody.

A secret is never handed to the model, never stored in memory, an AgentAction,
a run record, a log line or an MCP result. The provider resolves a name to a
value only for the infrastructure that is about to make an authorized request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Sequence

from app.domain.value_objects.entity_id import EntityId


class CredentialAccessDeniedError(PermissionError):
    """Raised when code without a credential grant asks for a secret.

    Message text never contains the secret or the provider's raw configuration.
    """


@dataclass(frozen=True, slots=True)
class CredentialGrant:
    """Authorization to resolve one credential, for one agent run, once."""

    credential_name: str
    agent_run_id: EntityId
    tool_name: str
    allowed_namespaces: frozenset[str] = frozenset()
    justification: str = ""

    def allows(self, credential_name: str) -> bool:
        if not self.allowed_namespaces:
            return True
        for namespace in self.allowed_namespaces:
            if credential_name == namespace or credential_name.startswith(f"{namespace}."):
                return True
        return False


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """A resolved secret. ``value`` is excluded from repr and never serialized."""

    name: str
    value: str = field(repr=False, default="")
    provider: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("credential name must not be empty")


class CredentialProviderPort(ABC):
    """Resolves credential names to values, under an explicit grant."""

    @abstractmethod
    def available_names(self) -> Sequence[str]:
        """Names this provider can resolve. Values are never enumerable."""
        raise NotImplementedError

    @abstractmethod
    def resolve(self, name: str, grant: CredentialGrant) -> ResolvedCredential:
        raise NotImplementedError

    def close(self) -> None:
        return None


class DenyAllCredentialProvider(CredentialProviderPort):
    """The default. Used whenever credential custody is not explicitly enabled."""

    def available_names(self) -> Sequence[str]:
        return ()

    def resolve(self, name: str, grant: CredentialGrant) -> ResolvedCredential:
        raise CredentialAccessDeniedError(
            f"credential access is not configured in this environment: {name}"
        )
