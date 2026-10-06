import pytest
from unittest.mock import AsyncMock, Mock

from app.application.agents.orchestrator import AgentOrchestrator
from app.application.security.approval_service import ApprovalService
from app.application.security.policy_engine import PolicyEngine
from app.application.security.policy_registry import PolicyRegistry
from app.application.security.trust_engine import TrustEngine
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.ports.agent_brain import AgentBrain, AgentDecision
from app.domain.ports.tool import ToolDefinition, ToolObservation
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.services.agent_run_state_service import AgentRunStateService
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from tests.support.repositories import InMemoryPermissionRequestRepository


@pytest.fixture
def mock_agent_brain():
    brain = Mock(spec=AgentBrain)
    brain.decide = AsyncMock()
    return brain


@pytest.fixture
def mock_tool_registry():
    registry = Mock(spec=ToolRegistry)
    return registry


@pytest.fixture
def mock_tool_executor():
    executor = Mock(spec=ToolExecutor)
    executor.execute = AsyncMock()
    return executor


@pytest.fixture
def mock_agent_action_repository():
    repo = Mock(spec=AgentActionRepository)
    return repo


@pytest.fixture
def mock_agent_run_repository():
    repo = Mock()
    repo.save = Mock()
    return repo


@pytest.fixture
def mock_permission_repository():
    repo = Mock(spec=PermissionRepository)
    repo.check_permission = Mock(return_value=True)
    return repo


@pytest.fixture
def trust_engine(mock_permission_repository):
    policy_registry = PolicyRegistry(permission_checker=None)
    policy_engine = policy_registry.create_policy_engine()
    return TrustEngine(policy_engine, mock_permission_repository)


@pytest.fixture
def permission_request_repository():
    return InMemoryPermissionRequestRepository()


@pytest.fixture
def approval_service(permission_request_repository):
    return ApprovalService(permission_request_repository)


@pytest.fixture
def orchestrator(
    mock_agent_brain,
    mock_tool_registry,
    mock_tool_executor,
    trust_engine,
    mock_agent_run_repository,
    mock_agent_action_repository,
    approval_service,
):
    context_builder = Mock()
    context_builder.build = Mock(return_value={})
    
    return AgentOrchestrator(
        agent_brain=mock_agent_brain,
        context_builder=context_builder,
        tool_registry=mock_tool_registry,
        tool_executor=mock_tool_executor,
        trust_engine=trust_engine,
        agent_run_repository=mock_agent_run_repository,
        agent_action_repository=mock_agent_action_repository,
        approval_service=approval_service,
        state_service=AgentRunStateService(),
    )


@pytest.fixture
def sample_agent_run():
    return AgentRun(
        agent_id=EntityId.new(),
        user_request="Create a task",
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


class TestAgentTrustIntegration:
    async def test_low_risk_action_executes_without_approval(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        mock_tool_executor,
        mock_agent_action_repository,
        low_risk_tool,
    ):
        # Setup: Brain decides to execute a low-risk tool, then finishes.
        mock_agent_brain.decide.side_effect = [
            AgentDecision(
                decision_type="TOOL_CALL",
                tool_name="tasks.search",
                arguments={"query": "test"},
            ),
            AgentDecision(decision_type="FINAL", response="done"),
        ]
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=low_risk_tool))
        mock_tool_registry.definitions.return_value = [low_risk_tool]
        mock_tool_executor.execute.return_value = ToolObservation(
            tool_name="tasks.search",
            success=True,
            output=[],
        )
        
        # Execute
        result = await orchestrator.execute(sample_agent_run)
        
        # Verify: Tool should execute without permission request
        assert result.run.status == AgentRunStatus.COMPLETED
        mock_tool_executor.execute.assert_called_once()
        # Verify action was approved and executed
        saved_actions = mock_agent_action_repository.save.call_args_list
        assert len(saved_actions) >= 2  # Save with APPROVED, then with COMPLETED

    async def test_medium_risk_action_requires_approval(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        mock_tool_executor,
        medium_risk_tool,
    ):
        # Setup: Brain decides to execute a medium-risk tool
        mock_agent_brain.decide.return_value = AgentDecision(
            decision_type="TOOL_CALL",
            tool_name="calendar.create",
            arguments={"title": "Meeting"},
        )
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=medium_risk_tool))
        mock_tool_registry.definitions.return_value = [medium_risk_tool]
        
        # Execute
        result = await orchestrator.execute(sample_agent_run)
        
        # Verify: Should pause for permission
        assert result.run.status == AgentRunStatus.WAITING_PERMISSION
        assert result.question is not None
        assert "calendar.create" in result.question
        # Tool should NOT be executed
        mock_tool_executor.execute.assert_not_called()

    async def test_high_risk_action_blocked(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        mock_tool_executor,
        high_risk_tool,
    ):
        # Setup: Brain decides to execute a high-risk tool
        mock_agent_brain.decide.return_value = AgentDecision(
            decision_type="TOOL_CALL",
            tool_name="credentials.access",
            arguments={},
        )
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=high_risk_tool))
        mock_tool_registry.definitions.return_value = [high_risk_tool]
        
        # Execute
        result = await orchestrator.execute(sample_agent_run)
        
        # Verify: Should be blocked
        assert result.run.status == AgentRunStatus.BLOCKED
        assert "blocked" in result.response.lower()
        # Tool should NOT be executed
        mock_tool_executor.execute.assert_not_called()

    async def test_resume_with_approval_executes_tool(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        mock_tool_executor,
        mock_agent_action_repository,
        medium_risk_tool,
    ):
        # Setup: Run is waiting for permission
        sample_agent_run.set_status(AgentRunStatus.WAITING_PERMISSION)
        
        # Create a pending action
        pending_action = AgentAction(
            agent_run_id=sample_agent_run.id,
            skill_name="calendar",
            action_name="calendar.create",
            arguments={"title": "Meeting"},
        )
        mock_agent_action_repository.list_by_run.return_value = [pending_action]
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=medium_risk_tool))
        mock_tool_executor.execute.return_value = ToolObservation(
            tool_name="calendar.create",
            success=True,
            output={"id": "123"},
        )
        
        # Resume with approval
        result = await orchestrator.resume(sample_agent_run, allow=True)
        
        # Verify: Tool should execute
        assert result.run.status == AgentRunStatus.COMPLETED
        mock_tool_executor.execute.assert_called_once()
        assert "completed" in result.response.lower()

    async def test_resume_with_rejection_blocks_action(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_action_repository,
        mock_tool_registry,
        medium_risk_tool,
    ):
        # Setup: Run is waiting for permission
        sample_agent_run.set_status(AgentRunStatus.WAITING_PERMISSION)
        
        # Create a pending action
        pending_action = AgentAction(
            agent_run_id=sample_agent_run.id,
            skill_name="calendar",
            action_name="calendar.create",
            arguments={"title": "Meeting"},
        )
        mock_agent_action_repository.list_by_run.return_value = [pending_action]
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=medium_risk_tool))
        
        # Resume with rejection
        result = await orchestrator.resume(sample_agent_run, allow=False)
        
        # Verify: Action should be blocked
        assert result.run.status == AgentRunStatus.BLOCKED
        assert "denied" in result.response.lower()

    async def test_permission_request_limit_blocks_execution(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        medium_risk_tool,
    ):
        # Setup: Configure orchestrator with low permission request limit
        orchestrator.max_permission_requests = 1
        
        # Setup: Brain requests multiple medium-risk actions
        mock_agent_brain.decide.return_value = AgentDecision(
            decision_type="TOOL_CALL",
            tool_name="calendar.create",
            arguments={"title": "Meeting"},
        )
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=medium_risk_tool))
        mock_tool_registry.definitions.return_value = [medium_risk_tool]
        
        # First execution should pause
        await orchestrator.execute(sample_agent_run)
        assert sample_agent_run.status == AgentRunStatus.WAITING_PERMISSION
        
        # Reset status and try again (simulating loop)
        sample_agent_run.set_status(AgentRunStatus.PLANNING)
        
        # Second execution should hit the limit
        result = await orchestrator.execute(sample_agent_run)
        
        # Verify: Should be blocked due to limit
        assert result.run.status == AgentRunStatus.BLOCKED
        assert "permission request limit" in result.response.lower()

    async def test_denied_action_limit_blocks_execution(
        self,
        orchestrator,
        sample_agent_run,
        mock_agent_brain,
        mock_tool_registry,
        high_risk_tool,
    ):
        # Setup: Configure orchestrator with low denied action limit
        orchestrator.max_denied_actions = 1
        
        # Setup: Brain requests high-risk actions (which get denied)
        mock_agent_brain.decide.return_value = AgentDecision(
            decision_type="TOOL_CALL",
            tool_name="credentials.access",
            arguments={},
        )
        mock_tool_registry.get.return_value = Mock(definition=Mock(return_value=high_risk_tool))
        mock_tool_registry.definitions.return_value = [high_risk_tool]
        
        # First execution should be blocked
        await orchestrator.execute(sample_agent_run)
        assert sample_agent_run.status == AgentRunStatus.BLOCKED
        
        # Reset status and try again (simulating loop)
        sample_agent_run.set_status(AgentRunStatus.PLANNING)
        
        # Second execution should hit the limit
        result = await orchestrator.execute(sample_agent_run)
        
        # Verify: Should be blocked due to limit
        assert result.run.status == AgentRunStatus.BLOCKED
        assert "denied action limit" in result.response.lower()
