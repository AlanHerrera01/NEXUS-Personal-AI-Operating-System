"""Credential providers.

``DenyAllCredentialProvider`` is the default and stays in force unless a
deployment explicitly opts in. ``EnvironmentCredentialProvider`` reads from the
process environment for local development; it is namespaced, so a grant for
``NEB_API`` cannot resolve ``NEB_API_SECRET``, and the value never leaves the
provider except through ``CredentialService.inject_into_request``.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Sequence

from app.domain.ports.credential_provider import (
    CredentialAccessDeniedError,
    CredentialGrant,
    CredentialProviderPort,
    DenyAllCredentialProvider,
    ResolvedCredential,
)

ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class EnvironmentCredentialProvider(CredentialProviderPort):
    """Resolves registered environment variables under an explicit grant."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = environ if environ is not None else os.environ

    def available_names(self) -> Sequence[str]:
        return tuple(
            name
            for name in sorted(self.environ)
            if name.startswith("NEXUS_CRED_") and ENV_NAME_PATTERN.match(name)
        )

    def resolve(self, name: str, grant: CredentialGrant) -> ResolvedCredential:
        if not self.available_names().__contains__(name):
            raise CredentialAccessDeniedError(
                f"credential access denied: {name} is not a registered credential"
            )
        value = self.environ.get(name, "")
        if not value:
            raise CredentialAccessDeniedError(
                f"credential access denied: {name} has no value in this environment"
            )
        return ResolvedCredential(name=name, value=value, provider="environment")


class ResolverPlaceholderCredentialProvider(CredentialProviderPort):
    """Hands the sandbox a resolver placeholder instead of the secret.

    This is the shape OpenShell uses for provider credentials: the agent and the
    model see ``openshell:resolve:env:NAME`` and the real value is substituted
    at the egress boundary, outside the sandbox. NEXUS mirrors the contract so
    the sandbox never holds a raw secret even when a tool is authorized to use
    one.
    """

    PREFIX = "openshell:resolve:env:"

    def __init__(self, names: Sequence[str] = ()) -> None:
        self.names = tuple(names)

    def available_names(self) -> Sequence[str]:
        return self.names

    def resolve(self, name: str, grant: CredentialGrant) -> ResolvedCredential:
        if name not in self.names:
            raise CredentialAccessDeniedError(
                f"credential access denied: {name} is not registered"
            )
        return ResolvedCredential(
            name=name, value=f"{self.PREFIX}{name}", provider="resolver-placeholder"
        )


__all__ = [
    "DenyAllCredentialProvider",
    "EnvironmentCredentialProvider",
    "ResolverPlaceholderCredentialProvider",
]
