import pytest
from unittest.mock import Mock

from app.application.security.policy_engine import PolicyEngine
from app.application.security.trust_engine import TrustEngine
from app.domain.ports.tool import ToolDefinition
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_evaluation import TrustEvaluation


@pytest.fixture
def mock_policy_engine():
    engine = Mock(spec=PolicyEngine)
    return engine


@pytest.fixture
def mock_permission_repository():
    repo = Mock(spec=PermissionRepository)
    return repo


@pytest.fixture
def trust_engine(mock_policy_engine, mock_permission_repository):
    return TrustEngine(
        policy_engine=mock_policy_engine,
        permission_repository=mock_permission_repository,
        default_decision=PermissionDecision.DENY,
    )


@pytest.fixture
def low_risk_tool():
    return ToolDefinition(
        name="tasks.search",
        description="Search tasks",
        input_schema={"type": "object"},
        skill_name="tasks",
        risk_level=RiskLevel.LOW,
        read_only=True,
        side_effect=False,
    )


@pytest.fixture
def medium_risk_tool():
    return ToolDefinition(
        name="calendar.create",
        description="Create calendar event",
        input_schema={"type": "object"},
        skill_name="calendar",
        risk_level=RiskLevel.MEDIUM,
        read_only=False,
        side_effect=True,
        requires_confirmation=True,
    )


@pytest.fixture
def high_risk_tool():
    return ToolDefinition(
        name="credentials.access",
        description="Access credentials",
        input_schema={"type": "object"},
        skill_name="credentials",
        risk_level=RiskLevel.HIGH,
        read_only=False,
        side_effect=True,
    )


class TestTrustEngine:
    def test_evaluate_allow(self, trust_engine, mock_policy_engine, low_risk_tool):
        from app.domain.value_objects.policy_result import PolicyResult
        
        mock_policy_engine.evaluate.return_value = PolicyResult.allow(
            "test_policy",
            "Low-risk read-only action is allowed"
        )
        
        user_id = EntityId.new()
        agent_id = EntityId.new()
        agent_run_id = EntityId.new()
        
        result = trust_engine.evaluate(
            low_risk_tool,
            user_id,
            agent_id,
            agent_run_id,
            {},
        )
        
        assert isinstance(result, TrustEvaluation)
        assert result.decision == PermissionDecision.ALLOW
        assert result.risk_level == RiskLevel.LOW
        assert result.requires_confirmation is False
        assert "allowed" in result.reason.lower()

    def test_evaluate_ask(self, trust_engine, mock_policy_engine, medium_risk_tool):
        from app.domain.value_objects.policy_result import PolicyResult
        
        mock_policy_engine.evaluate.return_value = PolicyResult.ask(
            "test_policy",
            "Medium-risk action requires confirmation"
        )
        
        user_id = EntityId.new()
        agent_id = EntityId.new()
        agent_run_id = EntityId.new()
        
        result = trust_engine.evaluate(
            medium_risk_tool,
            user_id,
            agent_id,
            agent_run_id,
            {},
        )
        
        assert isinstance(result, TrustEvaluation)
        assert result.decision == PermissionDecision.ASK
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.requires_confirmation is True
        assert "confirmation" in result.reason.lower()

    def test_evaluate_deny(self, trust_engine, mock_policy_engine, high_risk_tool):
        from app.domain.value_objects.policy_result import PolicyResult
        
        mock_policy_engine.evaluate.return_value = PolicyResult.deny(
            "test_policy",
            "High-risk action is not allowed"
        )
        
        user_id = EntityId.new()
        agent_id = EntityId.new()
        agent_run_id = EntityId.new()
        
        result = trust_engine.evaluate(
            high_risk_tool,
            user_id,
            agent_id,
            agent_run_id,
            {},
        )
        
        assert isinstance(result, TrustEvaluation)
        assert result.decision == PermissionDecision.DENY
        assert result.risk_level == RiskLevel.HIGH
        assert result.requires_confirmation is False
        assert "not allowed" in result.reason.lower()

    def test_evaluate_default_deny(self, trust_engine, mock_policy_engine, low_risk_tool):
        from app.domain.value_objects.policy_result import PolicyResult
        
        mock_policy_engine.evaluate.return_value = PolicyResult.not_applicable("test_policy")
        
        user_id = EntityId.new()
        agent_id = EntityId.new()
        agent_run_id = EntityId.new()
        
        result = trust_engine.evaluate(
            low_risk_tool,
            user_id,
            agent_id,
            agent_run_id,
            {},
        )
        
        assert isinstance(result, TrustEvaluation)
        assert result.decision == PermissionDecision.DENY
        assert result.policy_id == "default_deny"
        assert "default deny" in result.reason.lower()

    def test_check_permission(self, trust_engine, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        mock_permission_repository.check_permission.return_value = True
        
        result = trust_engine.check_permission(user_id, agent_id, "tasks", "tasks.search")
        
        assert result is True
        mock_permission_repository.check_permission.assert_called_once_with(
            user_id, agent_id, "tasks", "tasks.search"
        )

    def test_requires_confirmation_from_tool(self, trust_engine, mock_policy_engine, low_risk_tool):
        from app.domain.value_objects.policy_result import PolicyResult
        
        # Tool requires confirmation even though policy says ALLOW
        tool_with_confirmation = ToolDefinition(
            name="tasks.create",
            description="Create task",
            input_schema={"type": "object"},
            skill_name="tasks",
            risk_level=RiskLevel.LOW,
            read_only=False,
            side_effect=True,
            requires_confirmation=True,
        )
        
        mock_policy_engine.evaluate.return_value = PolicyResult.allow(
            "test_policy",
            "Action is allowed"
        )
        
        user_id = EntityId.new()
        agent_id = EntityId.new()
        agent_run_id = EntityId.new()
        
        result = trust_engine.evaluate(
            tool_with_confirmation,
            user_id,
            agent_id,
            agent_run_id,
            {},
        )
        
        assert result.requires_confirmation is True
