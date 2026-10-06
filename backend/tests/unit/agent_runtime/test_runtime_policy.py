from __future__ import annotations

import pytest

from app.application.agent_runtime.policy_factory import RuntimeBaseline, RuntimePolicyFactory
from app.application.agent_runtime.settings import RuntimeLimitsConfig
from app.domain.value_objects.network_mode import NetworkMode
from app.domain.value_objects.runtime_policy import (
    CredentialPolicy,
    FilesystemPolicy,
    NetworkEndpoint,
    NetworkPolicy,
    PolicyViolation,
    ProcessPolicy,
    ResourceLimits,
    RuntimePolicy,
)

WORKSPACE = "/srv/nexus/runs/abc"


def baseline(**overrides) -> RuntimeLimitsConfig:
    config = {
        "max_execution_seconds": 30.0,
        "max_output_bytes": 4096,
        "max_memory_mb": 256,
        "allowed_binaries": ("/usr/bin/ls",),
    }
    config.update(overrides)
    return RuntimeLimitsConfig(**config)


class TestPolicyInvariants:
    def test_default_policy_is_denied_everywhere(self) -> None:
        policy = RuntimePolicy()

        assert policy.network.mode is NetworkMode.DENY
        assert policy.allows_endpoint("api.example.com", 443) is False
        assert policy.allows_path("/etc/passwd") is False
        assert policy.credentials.allow_host_access is False

    def test_allow_all_network_mode_is_rejected(self) -> None:
        with pytest.raises(PolicyViolation):
            NetworkPolicy(mode=NetworkMode.ALLOW)

    def test_runtime_policy_rejects_allow_all_network(self) -> None:
        with pytest.raises(PolicyViolation):
            RuntimePolicy(network=NetworkPolicy(mode=NetworkMode.ALLOW))

    def test_deny_mode_cannot_carry_endpoints(self) -> None:
        with pytest.raises(PolicyViolation):
            NetworkPolicy(
                mode=NetworkMode.DENY,
                allowed_endpoints=(NetworkEndpoint(host="a.com", port=443),),
            )

    def test_isolation_intact_requires_every_invariant(self) -> None:
        assert RuntimePolicy().is_isolation_intact() is True

        not_workspace_only = RuntimePolicy(
            filesystem=FilesystemPolicy(
                workspace_only=False,
                workspace_path=WORKSPACE,
                read_write_paths=(WORKSPACE,),
            )
        )
        assert not_workspace_only.is_isolation_intact() is False

        privileged = RuntimePolicy(
            processes=ProcessPolicy(no_new_privileges=False)
        )
        assert privileged.is_isolation_intact() is False

        leaking = RuntimePolicy(
            credentials=CredentialPolicy(allow_host_access=True)
        )
        assert leaking.is_isolation_intact() is False

    def test_host_credential_access_breaks_isolation(self) -> None:
        policy = RuntimePolicy(
            credentials=CredentialPolicy(allow_runtime_injection=True)
        )

        assert policy.credentials.exposes_secrets_to_runtime is True
        assert policy.is_isolation_intact() is False


class TestPathJail:
    def test_only_workspace_paths_are_writable(self) -> None:
        policy = RuntimePolicy().with_workspace(WORKSPACE)

        assert policy.allows_path(WORKSPACE) is True
        assert policy.allows_path(f"{WORKSPACE}/nested/file.txt") is True
        assert policy.allows_path("/etc/passwd") is False
        assert policy.allows_path("/root/.bashrc") is False

    def test_prefix_collision_is_not_inside_the_workspace(self) -> None:
        policy = RuntimePolicy().with_workspace(WORKSPACE)

        # A sibling directory sharing the workspace's name prefix is a real
        # escape, so the check must be segment-aware rather than a string prefix.
        assert policy.allows_path(WORKSPACE + "-other/secret") is False

    @pytest.mark.parametrize("path", ["~/.ssh/id_rsa", "~/.aws/credentials", "/home/u/.ssh/k"])
    def test_home_credential_paths_are_never_allowed(self, path: str) -> None:
        assert RuntimePolicy().with_workspace(WORKSPACE).allows_path(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            f"{WORKSPACE}/../../../../etc",
            f"{WORKSPACE}/input/../../../..",
            f"{WORKSPACE}/./../other-run",
        ],
    )
    def test_traversal_out_of_the_workspace_is_refused(self, path: str) -> None:
        # The workspace string is still a prefix of these paths even though the
        # real location is elsewhere, so containment must canonicalise first.
        assert RuntimePolicy().with_workspace(WORKSPACE).allows_path(path) is False


class TestNetworkModeIsCoerced:
    """A mode that arrived as a plain ``str`` must not become a fail-open gap.

    Every check in the policy compares by identity (``is not NetworkMode.ALLOW``).
    A raw ``"ALLOW"`` string is equal by value but is *not* the enum member, so an
    uncoerced mode would slip past ``is_isolation_intact`` and open egress.
    """

    def test_a_string_mode_becomes_the_enum_member(self) -> None:
        policy = NetworkPolicy(mode="RESTRICTED")

        assert policy.mode is NetworkMode.RESTRICTED
        assert policy.is_restricted is True

    def test_a_string_allow_mode_is_rejected(self) -> None:
        with pytest.raises(PolicyViolation):
            NetworkPolicy(mode="ALLOW")

    def test_a_lowercase_string_allow_mode_is_still_rejected(self) -> None:
        with pytest.raises(PolicyViolation):
            NetworkPolicy(mode="allow")

    def test_coercion_keeps_isolation_intact_accurate(self) -> None:
        policy = RuntimePolicy().with_workspace(WORKSPACE)

        assert policy.is_isolation_intact() is True

    def test_describe_works_on_a_coerced_policy(self) -> None:
        policy = RuntimePolicy(network=NetworkPolicy(mode="DENY")).with_workspace(WORKSPACE)

        assert policy.describe()["network"]["mode"] == "DENY"


class TestBinaryAllowlist:
    def test_unlisted_binary_is_denied_when_execution_is_restricted(self) -> None:
        policy = RuntimePolicy(processes=ProcessPolicy(allowed_binaries=("/usr/bin/ls",)))

        assert policy.allows_binary("/usr/bin/ls") is True
        assert policy.allows_binary("/bin/sh") is False

    def test_empty_allowlist_means_unrestricted_execution(self) -> None:
        # An empty allowed_binaries tuple means "do not restrict", which is a
        # weaker posture and must not be mistaken for "nothing is allowed".
        policy = RuntimePolicy()

        assert policy.processes.is_execution_restricted is False
        assert policy.allows_binary("/bin/sh") is True


class TestRestrictTo:
    def test_intersection_never_widens_a_limit(self) -> None:
        generous = RuntimePolicy(resources=ResourceLimits(max_execution_seconds=60))
        strict = RuntimePolicy(resources=ResourceLimits(max_execution_seconds=10))

        assert restrict(generous, strict).resources.max_execution_seconds == 10
        assert restrict(strict, generous).resources.max_execution_seconds == 10

    def test_deny_network_wins_over_restricted(self) -> None:
        denied = RuntimePolicy()
        restricted = RuntimePolicy().with_endpoints(
            (NetworkEndpoint(host="a.com", port=443),)
        )

        assert restrict(denied, restricted).network.mode is NetworkMode.DENY
        assert restrict(restricted, denied).network.mode is NetworkMode.DENY

    def test_credentials_are_never_restored_by_intersection(self) -> None:
        wide = RuntimePolicy(credentials=CredentialPolicy(allow_host_access=True))
        narrow = RuntimePolicy()

        assert restrict(wide, narrow).credentials.allow_host_access is False
        assert restrict(narrow, wide).credentials.allow_host_access is False

    def test_expiration_takes_the_shorter(self) -> None:
        short = RuntimePolicy(expiration_seconds=60)
        long = RuntimePolicy(expiration_seconds=3600)

        assert restrict(short, long).expiration_seconds == 60


class TestPolicyFactory:
    def factory(self, **overrides) -> RuntimePolicyFactory:
        return RuntimePolicyFactory(
            RuntimeBaseline.from_config(baseline(**overrides))
        )

    def test_tool_without_network_gets_a_denied_network(self) -> None:
        policy = self.factory().for_tool(None, needs_network=False)

        assert policy.network.mode is NetworkMode.DENY

    def test_high_risk_tool_is_capped_at_one_call_and_no_network(self) -> None:
        from app.domain.ports.tool import ToolDefinition
        from app.domain.value_objects.risk_level import RiskLevel

        tool = ToolDefinition(
            name="danger.delete",
            description="delete",
            input_schema={},
            skill_name="danger",
            risk_level=RiskLevel.HIGH,
        )

        policy = self.factory().for_tool(tool, needs_network=True)

        assert policy.resources.max_tool_calls == 1
        assert policy.resources.max_network_requests == 0

    def test_requested_endpoint_outside_the_baseline_is_dropped(self) -> None:
        policy = self.factory(
            allowed_network_endpoints=(("api.example.com", 443, "read-only"),)
        ).for_tool(
            None,
            requested_endpoints=(
                NetworkEndpoint(host="api.example.com", port=443),
                NetworkEndpoint(host="evil.example.com", port=443),
            ),
            needs_network=True,
        )

        assert policy.allows_endpoint("api.example.com", 443) is True
        assert policy.allows_endpoint("evil.example.com", 443) is False

    def test_policy_carries_no_secret_in_its_description(self) -> None:
        described = RuntimePolicy(
            credentials=CredentialPolicy(allowed_credential_names=frozenset({"NEBRUS_API_KEY"}))
        ).describe()

        rendered = str(described)
        assert "NEBRUS_API_KEY" not in rendered
        assert "allow_host_access" in rendered


def restrict(left: RuntimePolicy, right: RuntimePolicy) -> RuntimePolicy:
    return left.restrict_to(right)