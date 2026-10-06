"""The event ingress must be closed unless it is explicitly opened.

NEXUS has no authentication layer, so this endpoint is the only place in the
codebase where a caller proves anything. That makes its failure modes worth
pinning down precisely, because "there is no default secret" is only a real
guarantee if it is asserted:

* no secret configured -> every request refused, not treated as open;
* wrong secret -> refused;
* no secret supplied at all -> refused;
* the flag off -> 503 even with a valid secret, so a disabled deployment cannot
  start work.

The negative cases matter more than the happy path here. A permissive default
would be invisible in review and would ship as an open webhook that fans out into
agent runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.always_on.event_source import INGRESS_HEADER, IngressAuthenticator
from app.main import app
from app.presentation.dependencies.identity import LOCAL_USER_ID
from app.presentation.dependencies.always_on import (
    get_ingress_authenticator,
    get_trigger_event_service,
)

SECRET = "an-ingress-secret-of-sufficient-length"
BODY = {
    "event_type": "calendar.invite",
    "idempotency_key": "delivery-0001",
    "payload": {"summary": "standup"},
}


@dataclass
class StubIngest:
    """Captures the call instead of touching a database."""

    calls: list[dict] = field(default_factory=list)

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)

        class _Event:
            id = EntityId.new()
            processed_at = None

        class _Report:
            event = _Event()
            duplicate = False
            matched_jobs = 1
            outcomes: list = []
            errors: list = []

            def count(self, outcome_type) -> int:
                return 0

        return _Report()


@pytest.fixture
def client():
    stub = StubIngest()
    app.dependency_overrides[get_ingress_authenticator] = (
        lambda: IngressAuthenticator(get_settings().always_on_event_ingress_secret)
    )
    app.dependency_overrides[get_trigger_event_service] = lambda: stub
    try:
        with TestClient(app) as test_client:
            test_client.stub = stub
            yield test_client
    finally:
        # Remove only the keys this module added. `dependency_overrides.clear()`
        # would also wipe the module-level override that tests/test_memory_api.py
        # installs at import time, silently sending that suite at the real
        # database -- which is how this was found, by that suite failing.
        app.dependency_overrides.pop(get_ingress_authenticator, None)
        app.dependency_overrides.pop(get_trigger_event_service, None)
        app.dependency_overrides.pop(get_settings, None)


def _post(client, header_value=..., body=BODY):
    headers = {}
    if header_value is not ...:
        headers[INGRESS_HEADER] = header_value
    return client.post("/api/v1/events/trigger", json=body, headers=headers)


class TestIngressIsClosedByDefault:
    def test_unset_secret_refuses_every_request(self) -> None:
        """An unconfigured ingress is closed, not open.

        This is the assertion that makes "there is no default secret" mean
        something. Treating unset as allow-all would turn a missing config
        variable into an unauthenticated endpoint that starts agent runs.
        """
        assert IngressAuthenticator(None).verify(SECRET) is False
        assert IngressAuthenticator(None).verify("") is False
        assert IngressAuthenticator(None).verify(None) is False

    def test_empty_secret_is_treated_as_unset(self) -> None:
        assert IngressAuthenticator("").verify(SECRET) is False

    def test_missing_header_is_refused(self) -> None:
        authenticator = IngressAuthenticator(SECRET)
        assert authenticator.verify(None) is False
        assert authenticator.verify("") is False

    def test_wrong_secret_is_refused(self) -> None:
        authenticator = IngressAuthenticator(SECRET)
        assert authenticator.verify("wrong-but-long-enough-value") is False

    def test_correct_secret_is_accepted(self) -> None:
        assert IngressAuthenticator(SECRET).verify(SECRET) is True

    def test_prefix_of_the_secret_is_refused(self) -> None:
        """Guards against a comparison that stops at the first mismatch."""
        authenticator = IngressAuthenticator(SECRET)
        assert authenticator.verify(SECRET[:-1]) is False

    def test_secret_with_trailing_space_is_refused(self) -> None:
        authenticator = IngressAuthenticator(SECRET)
        assert authenticator.verify(f"{SECRET} ") is False


class TestIngressEndpoint:
    def test_unauthenticated_request_is_401_and_never_dispatches(self, client) -> None:
        response = _post(client, header_value="not-the-secret")
        assert response.status_code == 401
        assert client.stub.calls == []

    def test_absent_header_is_401(self, client) -> None:
        response = _post(client)
        assert response.status_code == 401
        assert client.stub.calls == []

    def test_unauthenticated_response_does_not_reveal_which_fault(
        self, client
    ) -> None:
        """A missing header and a wrong one must be indistinguishable.

        Otherwise the endpoint reports whether the deployment has a secret
        configured, which is reconnaissance for no benefit to the caller.
        """
        missing = _post(client)
        wrong = _post(client, header_value="wrong-but-long-enough-value")
        assert missing.status_code == wrong.status_code == 401
        assert missing.json()["detail"] == wrong.json()["detail"]


class TestFlagGating:
    def test_job_creation_is_refused_while_disabled(self, client) -> None:
        """The default deployment must not accept new scheduled work.

        Refusing is the point: creating a job nothing will ever run leaves the
        user believing they have set something up.
        """
        if get_settings().always_on_enabled:
            pytest.skip("always_on_enabled is on in this environment")

        response = client.post(
            "/api/v1/scheduled-jobs",
            json={
                "agent_id": "00000000-0000-0000-0000-000000000001",
                "name": "daily summary",
                "trigger_type": "CRON",
                "cron_expression": "0 9 * * *",
            },
        )
        assert response.status_code == 503


class TestAuthenticatedIngressReachesTheService:
    def test_valid_secret_and_enabled_flag_dispatch(self, client) -> None:
        """The happy path, so the negative tests above cannot pass vacuously."""
        enabled = get_settings().model_copy(
            update={
                "always_on_enabled": True,
                "always_on_event_ingress_secret": SECRET,
            }
        )
        app.dependency_overrides[get_settings] = lambda: enabled
        app.dependency_overrides[get_ingress_authenticator] = (
            lambda: IngressAuthenticator(SECRET)
        )
        try:
            response = _post(client, header_value=SECRET)
        finally:
            app.dependency_overrides.pop(get_settings, None)

        assert response.status_code == 202
        assert len(client.stub.calls) == 1
        assert client.stub.calls[0]["event_type"] == "calendar.invite"
        # Ownership is pinned by the server, never taken from the payload: a
        # caller cannot choose whose jobs their event reaches.
        assert client.stub.calls[0]["user_id"] == EntityId(LOCAL_USER_ID)

    def test_valid_secret_but_feature_off_is_503(self, client) -> None:
        enabled = get_settings().model_copy(
            update={
                "always_on_enabled": False,
                "always_on_event_ingress_secret": SECRET,
            }
        )
        app.dependency_overrides[get_settings] = lambda: enabled
        app.dependency_overrides[get_ingress_authenticator] = (
            lambda: IngressAuthenticator(SECRET)
        )
        try:
            response = _post(client, header_value=SECRET)
        finally:
            app.dependency_overrides.pop(get_settings, None)

        assert response.status_code == 503
        assert client.stub.calls == []