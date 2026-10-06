import pytest

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext
from app.infrastructure.security.policies.destructive_action import DestructiveActionPolicy
from app.infrastructure.security.policies.disabled_skill import DisabledSkillPolicy
from app.infrastructure.security.policies.high_risk import HighRiskPolicy
from app.infrastructure.security.policies.low_readonly import LowReadonlyPolicy
from app.infrastructure.security.policies.medium_risk import MediumRiskPolicy
from app.infrastructure.security.policies.sensitive_resource import SensitiveResourcePolicy


@pytest.fixture
def sample_context():
    return TrustContext(
        user_id=EntityId.new(),
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        tool_name="tasks.create",
        skill_name="tasks",
        risk_level=RiskLevel.LOW,
        read_only=False,
        side_effect=True,
    )


class TestHighRiskPolicy:
    def test_deny_high_risk(self, sample_context):
        policy = HighRiskPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="credential.access",
            skill_name="credentials",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.DENY
        assert "High-risk" in result.reason

    def test_not_applicable_low_risk(self, sample_context):
        policy = HighRiskPolicy()
        result = policy.evaluate(sample_context)
        assert result.applicable is False

    def test_not_applicable_medium_risk(self, sample_context):
        policy = HighRiskPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="tasks.create",
            skill_name="tasks",
            risk_level=RiskLevel.MEDIUM,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is False


class TestMediumRiskPolicy:
    def test_ask_medium_risk(self, sample_context):
        policy = MediumRiskPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="calendar.create",
            skill_name="calendar",
            risk_level=RiskLevel.MEDIUM,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.ASK
        assert "Medium-risk" in result.reason

    def test_not_applicable_low_risk(self, sample_context):
        policy = MediumRiskPolicy()
        result = policy.evaluate(sample_context)
        assert result.applicable is False

    def test_not_applicable_high_risk(self, sample_context):
        policy = MediumRiskPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="credential.access",
            skill_name="credentials",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is False


class TestLowReadonlyPolicy:
    def test_allow_low_readonly(self, sample_context):
        policy = LowReadonlyPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="tasks.search",
            skill_name="tasks",
            risk_level=RiskLevel.LOW,
            read_only=True,
            side_effect=False,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.ALLOW
        assert "Low-risk read-only" in result.reason

    def test_not_applicable_low_with_side_effect(self, sample_context):
        policy = LowReadonlyPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="tasks.create",
            skill_name="tasks",
            risk_level=RiskLevel.LOW,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is False

    def test_not_applicable_medium_risk(self, sample_context):
        policy = LowReadonlyPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="calendar.search",
            skill_name="calendar",
            risk_level=RiskLevel.MEDIUM,
            read_only=True,
            side_effect=False,
        )
        result = policy.evaluate(context)
        assert result.applicable is False


class TestDisabledSkillPolicy:
    def test_deny_disabled_skill(self, sample_context):
        policy = DisabledSkillPolicy(disabled_skills=frozenset({"credentials"}))
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="credentials.get",
            skill_name="credentials",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.DENY
        assert "disabled" in result.reason

    def test_not_applicable_enabled_skill(self, sample_context):
        policy = DisabledSkillPolicy(disabled_skills=frozenset({"credentials"}))
        result = policy.evaluate(sample_context)
        assert result.applicable is False


class TestSensitiveResourcePolicy:
    def test_deny_credential_access(self, sample_context):
        policy = SensitiveResourcePolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="credentials.get_api_key",
            skill_name="credentials",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.DENY
        assert "sensitive" in result.reason

    def test_deny_password_in_arguments(self, sample_context):
        policy = SensitiveResourcePolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="auth.login",
            skill_name="auth",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
            arguments={"password": "secret123"},
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.DENY

    def test_not_applicable_safe_tool(self, sample_context):
        policy = SensitiveResourcePolicy()
        result = policy.evaluate(sample_context)
        assert result.applicable is False


class TestDestructiveActionPolicy:
    def test_ask_delete_action(self, sample_context):
        policy = DestructiveActionPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="tasks.delete",
            skill_name="tasks",
            risk_level=RiskLevel.MEDIUM,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.ASK
        assert "Destructive" in result.reason

    def test_ask_drop_action(self, sample_context):
        policy = DestructiveActionPolicy()
        context = TrustContext(
            user_id=sample_context.user_id,
            agent_id=sample_context.agent_id,
            agent_run_id=sample_context.agent_run_id,
            tool_name="database.drop_table",
            skill_name="database",
            risk_level=RiskLevel.HIGH,
            read_only=False,
            side_effect=True,
        )
        result = policy.evaluate(context)
        assert result.applicable is True
        assert result.decision == PermissionDecision.ASK

    def test_not_applicable_safe_action(self, sample_context):
        policy = DestructiveActionPolicy()
        result = policy.evaluate(sample_context)
        assert result.applicable is False
