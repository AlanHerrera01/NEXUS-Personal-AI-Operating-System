"""Authentication for the external event ingress.

NEXUS has no user authentication layer (see the Phase 12 docs; the existing
``permission_requests`` routes still take a literal ``default-user-id``). That
means there is no existing identity mechanism for an external webhook to
present, and inventing a plausible-looking one -- a trusted-looking header, a
signed-but-unverified field -- would create a false impression that the ingress
is authenticated when it is not.

So the ingress uses the one mechanism that is actually verifiable today: a
shared secret held in configuration, compared in constant time. Its properties,
stated plainly:

* it genuinely authenticates the *caller* to a specific deployment, because the
  secret is never sent to the browser and never shipped in the frontend;
* it does **not** identify which *user* an event belongs to. The ingress binds
  events to the single configured ingress user, so a valid caller can only ever
  trigger that user's jobs. Multi-tenant deployment needs the real auth layer
  first;
* when no secret is configured, every request is refused. There is no default
  secret and no "development mode allows everything", because a default secret
  is a publicly-known secret.

When the proper auth layer lands, this is the piece that gets replaced. The
service behind it (:class:`TriggerEventService`) already takes ``user_id`` as a
parameter and does no identity handling of its own, so nothing else changes.
"""

import logging
import secrets

logger = logging.getLogger(__name__)

#: Header carrying the shared secret.
INGRESS_HEADER = "X-NEXUS-Ingress-Secret"


class IngressAuthenticator:
    """Constant-time verification of the event ingress shared secret."""

    def __init__(self, secret: str | None) -> None:
        self._secret = secret or ""

    @property
    def is_configured(self) -> bool:
        return bool(self._secret)

    def verify(self, presented: str | None) -> bool:
        """True only when a configured secret matches ``presented``.

        Refuses when nothing is configured. An unset secret means the deployment
        never opted into an ingress, and treating "unset" as "anything goes"
        would turn a missing configuration into an open door.
        """
        if not self._secret:
            return False
        if not presented:
            return False
        # compare_digest keeps the comparison time independent of how many
        # leading characters happen to match, so the endpoint cannot be used as
        # an oracle to recover the secret byte by byte.
        return secrets.compare_digest(presented, self._secret)


class InMemoryEventSource:
    """An :class:`EventSourcePort` fed by hand. For tests and local development.

    Ships in production source rather than under ``tests/`` so that a deployment
    without a real integration still has a working ingress path to exercise, and
    so importing it never requires a test framework.
    """

    def __init__(self, source_name: str = "in-memory") -> None:
        self._source_name = source_name
        self._pending: list = []

    @property
    def source_name(self) -> str:
        return self._source_name

    def publish(self, event) -> None:
        """Queue a :class:`RawEvent` for the next :meth:`poll`."""
        self._pending.append(event)

    async def poll(self, since):
        """Drain the queue in the order events were published.

        ``since`` is accepted to satisfy the port but deliberately unused: a
        :class:`RawEvent` carries no timestamp of its own, and inventing one
        here would mean this adapter filtering on a field nothing else in the
        system reads. Duplicates are likewise passed straight through -- the
        database is the only place a repeat can be recognised authoritatively
        across processes.
        """
        drained = list(self._pending)
        self._pending = []
        return drained