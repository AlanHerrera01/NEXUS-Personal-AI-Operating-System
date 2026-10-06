from __future__ import annotations

import pytest
import yaml

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
from app.infrastructure.agent_runtime.policies.openshell_policy_renderer import (
    MAX_POLICY_PATHS,
    OpenShellPolicyRenderer,
)

WORKSPACE = "/sandbox/nexus-run"


@pytest.fixture
def renderer() -> OpenShellPolicyRenderer:
    return OpenShellPolicyRenderer()


class TestDocumentShape:
    def test_document_declares_schema_version_one(self, renderer: OpenShellPolicyRenderer) -> None:
        document = renderer.render(RuntimePolicy().with_workspace(WORKSPACE), WORKSPACE)

        assert document["version"] == 1

    def test_landlock_is_a_hard_requirement(self, renderer: OpenShellPolicyRenderer) -> None:
        # `best_effort` would let the sandbox start without LSM enforcement,
        # which is the difference between "isolated" and "hoped for".
        document = renderer.render(RuntimePolicy(), WORKSPACE)

        assert document["landlock"]["compatibility"] == "hard_requirement"

    def test_workdir_inclusion_follows_the_workspace(self, renderer: OpenShellPolicyRenderer) -> None:
        document = renderer.render(RuntimePolicy().with_workspace(WORKSPACE), WORKSPACE)

        assert document["filesystem_policy"]["include_workdir"] is True

    def test_paths_are_emitted_as_posix(self, renderer: OpenShellPolicyRenderer) -> None:
        policy = RuntimePolicy(
            filesystem=FilesystemPolicy(
                workspace_path=r"C:\nexus\runs\abc",
                read_only_paths=(r"C:\usr",),
                read_write_paths=(r"C:\nexus\runs\abc",),
            )
        )

        document = renderer.render(policy, r"C:\nexus\runs\abc")

        # Backslashes would be inert inside a Linux sandbox, so they are
        # normalised. The renderer does not invent a drive-to-mount mapping;
        # translating a host path into a sandbox path is the workspace layer's
        # job, not this pure translation's.
        assert document["filesystem_policy"]["read_only"] == ["C:/usr"]
        assert document["filesystem_policy"]["read_write"] == ["C:/nexus/runs/abc"]
        assert "\\" not in yaml.safe_dump(document)

    def test_oversized_policy_is_refused(self, renderer: OpenShellPolicyRenderer) -> None:
        policy = RuntimePolicy(
            filesystem=FilesystemPolicy(
                workspace_path=WORKSPACE,
                read_only_paths=tuple(f"/opt/{index}" for index in range(MAX_POLICY_PATHS + 1)),
                read_write_paths=(),
            )
        )

        with pytest.raises(ValueError):
            renderer.render(policy, WORKSPACE)


class TestNetworkRendering:
    def test_deny_policy_renders_no_network_section(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        document = renderer.render(RuntimePolicy(), WORKSPACE)

        assert "network_policies" not in document

    def test_enforcement_is_always_enforce(self, renderer: OpenShellPolicyRenderer) -> None:
        # `audit` logs a denied request and lets it through.
        policy = RuntimePolicy().with_endpoints(
            (NetworkEndpoint(host="api.example.com", port=443),)
        )

        document = renderer.render(policy, WORKSPACE)
        endpoint = document["network_policies"]["nexus_egress"]["endpoints"][0]

        assert endpoint["enforcement"] == "enforce"

    def test_protocol_is_always_named(self, renderer: OpenShellPolicyRenderer) -> None:
        # Omitting `protocol` would downgrade an L7 rule to a bare host/port
        # allow, so the renderer always emits it.
        policy = RuntimePolicy().with_endpoints(
            (NetworkEndpoint(host="api.example.com", port=443, protocol="rest"),)
        )

        document = renderer.render(policy, WORKSPACE)

        assert document["network_policies"]["nexus_egress"]["endpoints"][0]["protocol"] == "rest"

    def test_tcp_endpoint_carries_no_request_rules(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        policy = RuntimePolicy().with_endpoints(
            (
                NetworkEndpoint(
                    host="db.example.com", port=5432, protocol="tcp", path="/ignored"
                ),
            )
        )

        endpoint = renderer.render(policy, WORKSPACE)["network_policies"]["nexus_egress"][
            "endpoints"
        ][0]

        assert endpoint == {
            "host": "db.example.com",
            "port": 5432,
            "enforcement": "enforce",
            "protocol": "tcp",
        }

    def test_read_only_endpoint_is_granted_get_not_a_wildcard(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        policy = RuntimePolicy().with_endpoints(
            (
                NetworkEndpoint(
                    host="api.example.com",
                    port=443,
                    protocol="rest",
                    path="/v1/*",
                    access="read-only",
                ),
            )
        )

        endpoint = renderer.render(policy, WORKSPACE)["network_policies"]["nexus_egress"][
            "endpoints"
        ][0]

        assert endpoint["rules"] == [{"allow": {"method": "GET", "path": "/v1/*"}}]

    def test_read_write_endpoint_is_granted_post(self, renderer: OpenShellPolicyRenderer) -> None:
        policy = RuntimePolicy().with_endpoints(
            (
                NetworkEndpoint(
                    host="api.example.com",
                    port=443,
                    protocol="rest",
                    path="/v1/items",
                    access="read-write",
                ),
            )
        )

        endpoint = renderer.render(policy, WORKSPACE)["network_policies"]["nexus_egress"][
            "endpoints"
        ][0]

        assert endpoint["rules"] == [{"allow": {"method": "POST", "path": "/v1/items"}}]

    def test_full_access_endpoint_keeps_the_wildcard(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        policy = RuntimePolicy().with_endpoints(
            (
                NetworkEndpoint(
                    host="api.example.com",
                    port=443,
                    protocol="rest",
                    path="*",
                    access="full",
                ),
            )
        )

        endpoint = renderer.render(policy, WORKSPACE)["network_policies"]["nexus_egress"][
            "endpoints"
        ][0]

        assert endpoint["rules"] == [{"allow": {"method": "*", "path": "*"}}]

    def test_allowed_binaries_become_endpoint_scoped_programs(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        policy = RuntimePolicy(
            network=NetworkPolicy(
                mode=NetworkMode.RESTRICTED,
                allowed_endpoints=(NetworkEndpoint(host="api.example.com", port=443),),
                allowed_binaries=("/usr/bin/curl",),
            )
        )

        document = renderer.render(policy, WORKSPACE)

        assert document["network_policies"]["nexus_egress"]["binaries"] == [
            {"path": "/usr/bin/curl"}
        ]


class TestNoSecretsInTheDocument:
    def test_credential_names_never_reach_the_policy_file(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        policy = RuntimePolicy(
            credentials=CredentialPolicy(allowed_credential_names=frozenset({"NEBIUS_API_KEY"}))
        )

        rendered = yaml.safe_dump(renderer.render(policy, WORKSPACE))

        assert "NEBIUS_API_KEY" not in rendered
        assert "credential" not in rendered.lower() or "allowed_credential_names" not in rendered


class TestProcessSection:
    def test_process_identity_is_carried_through(self, renderer: OpenShellPolicyRenderer) -> None:
        policy = RuntimePolicy(processes=ProcessPolicy(run_as_user="nexus", run_as_group="nexus"))

        document = renderer.render(policy, WORKSPACE)

        assert document["process"]["run_as_user"] == "nexus"
        assert document["process"]["run_as_group"] == "nexus"

    def test_a_policy_naming_root_as_the_runtime_user_cannot_be_constructed(self) -> None:
        from app.domain.value_objects.runtime_policy import PolicyViolation

        with pytest.raises(PolicyViolation):
            ProcessPolicy(run_as_user="0", run_as_group="0")

    def test_resource_limits_are_not_misrepresented_as_policy_fields(
        self, renderer: OpenShellPolicyRenderer
    ) -> None:
        # CPU and memory are applied by the runtime at creation time, not by the
        # policy document. Emitting them here would imply enforcement that the
        # schema does not provide.
        policy = RuntimePolicy(resources=ResourceLimits(max_memory_mb=256))

        document = renderer.render(policy, WORKSPACE)

        assert "resources" not in document
        assert "memory" not in document
        assert "cpu" not in document