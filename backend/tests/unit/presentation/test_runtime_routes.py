"""The runtime API must not become a reconnaissance surface.

These are contract tests on the response shape. NEXUS has no authentication
layer yet, so the routes cannot enforce access control; what they must still not
do is hand a caller the server's filesystem layout while trying.
"""

from __future__ import annotations

import pytest

from app.domain.entities._common import utc_now
from app.domain.entities.runtime_session import RuntimeSession
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState
from app.presentation.api.runtime_routes import RuntimeSessionResponse


def session(workspace_path: str) -> RuntimeSession:
    return RuntimeSession(
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        provider=RuntimeProvider.LOCAL,
        policy=RuntimePolicy(),
        workspace_path=workspace_path,
        expires_at=utc_now(),
    )


class TestSessionResponseDoesNotLeakHostPaths:
    @pytest.mark.parametrize(
        "workspace_path",
        [
            "/srv/nexus/runtime/runs/8be89ede-891b-4cc5-acf3-12110d11606f",
            "C:\\nexus\\runtime\\runs\\8be89ede-891b-4cc5-acf3-12110d11606f",
            "/home/deploy/.nexus-runtime/runs/abc",
        ],
    )
    def test_the_serialised_response_carries_no_host_path(
        self, workspace_path: str
    ) -> None:
        response = RuntimeSessionResponse.from_entity(session(workspace_path))

        rendered = response.model_dump_json()
        assert workspace_path not in rendered
        assert "runs" not in rendered
        assert "workspace_path" not in rendered

    def test_the_response_still_reports_the_run_it_belongs_to(self) -> None:
        # Scoping by run is the property these routes actually provide, so it
        # must survive the removal of the path.
        entity = session("/srv/nexus/runtime/runs/abc")
        response = RuntimeSessionResponse.from_entity(entity)

        assert response.agent_run_id == str(entity.agent_run_id)

    def test_the_policy_summary_contains_no_credential_values(self) -> None:
        response = RuntimeSessionResponse.from_entity(session("/srv/nexus/runs/abc"))

        rendered = response.model_dump_json()
        assert "sk-" not in rendered
        assert response.policy["credentials"]["allow_runtime_injection"] is False