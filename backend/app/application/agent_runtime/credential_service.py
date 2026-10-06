"""Credential custody at the application boundary.

The rule this service enforces: a secret is resolved only for infrastructure
that is about to perform an authorized request, under an explicit grant bound to
one agent run. Nothing here returns a value into an LLM context, an AgentAction,
a run record, a log line or an MCP result.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from app.application.agent_runtime.events import RuntimeEventRecorder
from app.domain.ports.credential_provider import (
    CredentialAccessDeniedError,
    CredentialGrant,
    CredentialProviderPort,
    ResolvedCredential,
)
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_event_type import SecurityEventType

logger = logging.getLogger(__name__)


class CredentialService:
    """Guards every read of a secret behind a grant and an audit record."""

    def __init__(
        self,
        provider: CredentialProviderPort,
        events: RuntimeEventRecorder | None = None,
    ) -> None:
        self.provider = provider
        self.events = events or RuntimeEventRecorder()

    def available_names(self) -> Sequence[str]:
        return self.provider.available_names()

    def issue_grant(
        self,
        *,
        credential_name: str,
        agent_run_id: EntityId,
        tool_name: str,
        allowed_namespaces: frozenset[str] = frozenset(),
        justification: str = "",
    ) -> CredentialGrant:
        return CredentialGrant(
            credential_name=credential_name,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            allowed_namespaces=allowed_namespaces,
            justification=justification,
        )

    def resolve(self, name: str, grant: CredentialGrant) -> ResolvedCredential:
        """Resolve a secret, or refuse. The refusal path is audited."""
        if not grant.allows(name):
            self._deny(name, grant, "credential is outside the grant namespace")
            raise CredentialAccessDeniedError(
                f"credential access denied: {name} is not covered by the grant"
            )
        if name not in self.provider.available_names():
            self._deny(name, grant, "credential is not registered with the provider")
            raise CredentialAccessDeniedError(
                f"credential access denied: {name} is not registered"
            )
        try:
            return self.provider.resolve(name, grant)
        except CredentialAccessDeniedError:
            self._deny(name, grant, "provider refused the credential")
            raise

    def inject_into_request(
        self,
        name: str,
        grant: CredentialGrant,
        build_request: Callable[[str], Any],
    ) -> Any:
        """Resolve a credential and hand it straight to a request builder.

        The value never becomes a return value of this service, so it cannot be
        logged, serialized into an observation, or placed in a model context.
        """
        credential = self.resolve(name, grant)
        logger.info("credential %s resolved for tool %s", name, grant.tool_name)
        return build_request(credential.value)

    def _deny(self, name: str, grant: CredentialGrant, reason: str) -> None:
        self.events.security(
            SecurityEventType.CREDENTIAL_ACCESS_DENIED,
            agent_run_id=grant.agent_run_id,
            tool_id=grant.tool_name,
            detail=reason,
            credential_name=name,
        )
