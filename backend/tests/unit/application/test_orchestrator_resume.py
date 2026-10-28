import asyncio
import pytest

from app.application.agents.orchestrator import AgentOrchestrator
from app.application.agents.context_builder import AgentContextBuilder
from app.application.security.approval_service import ApprovalService
from app.application.tools.executor import RegistryToolExecutor
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentDecision
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition, ToolResult
from app.infrastructure.security.trust_engine import DeterministicTrustEngine
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from tests.support.repositories import InMemoryPermissionRequestRepository
from tests.unit.application.test_orchestrator import FakeActionRepository, FakeRunRepository, SequenceBrain


class ConfirmationTool(Tool):
    def definition(self):
        return ToolDefinition("calendar.create", "Create event", {"type": "object"}, "calendar", RiskLevel.MEDIUM, True)

    async def execute(self, arguments, context: ToolContext):
        return ToolResult(True, "calendar.create", {"created": True})


def _orchestrator(brain, tool, actions):
    """An orchestrator wired with a real approval service.

    Resume refuses to proceed without a pending permission request to match
    against, and that request is created by ``execute`` only when an approval
    service is present. Wiring one here is what lets these tests exercise the
    approve/reject state machine instead of the "no request to resume" path.
    """
    registry = InMemoryToolRegistry([tool])
    return AgentOrchestrator(
        brain,
        AgentContextBuilder(None, registry), registry, RegistryToolExecutor(registry),
        DeterministicTrustEngine(), FakeRunRepository(), actions,
        approval_service=ApprovalService(InMemoryPermissionRequestRepository()),
        max_iterations=2,
    )


def test_resume_allow_executes_pending_action() -> None:
    # The action requires confirmation, so execute parks on an ASK. Approving
    # satisfies that ASK and the action must actually run -- this is the loop
    # that used to re-ask forever and never execute.
    tool = ConfirmationTool()
    actions = FakeActionRepository()
    orchestrator = _orchestrator(
        SequenceBrain(AgentDecision.tool_call("calendar.create", {})), tool, actions
    )
    run = AgentRun(EntityId.new(), "Create an event", user_id=EntityId.new())
    pending = asyncio.run(orchestrator.execute(run, user_id=str(run.user_id)))
    completed = asyncio.run(
        orchestrator.resume(run, True, user_id=str(run.user_id))
    )

    assert pending.question == "Allow calendar.create?"
    assert completed.run.status.value == "COMPLETED"
    assert actions.items[-1].status.value == "COMPLETED"


def test_resume_deny_blocks_pending_action() -> None:
    orchestrator = _orchestrator(
        SequenceBrain(AgentDecision.tool_call("calendar.create", {})),
        ConfirmationTool(),
        FakeActionRepository(),
    )
    run = AgentRun(EntityId.new(), "Create an event", user_id=EntityId.new())
    asyncio.run(orchestrator.execute(run, user_id=str(run.user_id)))
    blocked = asyncio.run(
        orchestrator.resume(run, False, user_id=str(run.user_id))
    )

    assert blocked.run.status.value == "BLOCKED"
    assert blocked.response == "Action denied by user"


def test_resume_without_an_identity_is_refused() -> None:
    """A run parked on an approval must not be resumable anonymously.

    Resume drives a state transition and mints a fresh authorization. Accepting
    it without an identity would mean the caller who answers the prompt is not
    the person the request was raised for -- and the permission request carries
    an owner precisely so that check is possible.
    """
    registry = InMemoryToolRegistry([ConfirmationTool()])
    orchestrator = AgentOrchestrator(
        SequenceBrain(AgentDecision.tool_call("calendar.create", {})),
        AgentContextBuilder(None, registry), registry, RegistryToolExecutor(registry),
        DeterministicTrustEngine(), FakeRunRepository(), FakeActionRepository(),
        max_iterations=2,
    )
    run = AgentRun(EntityId.new(), "Create an event", user_id=EntityId.new())
    asyncio.run(orchestrator.execute(run, user_id=str(run.user_id)))

    with pytest.raises(Exception):
        asyncio.run(orchestrator.resume(run, True))


def test_answering_a_permission_wait_is_refused() -> None:
    """Answering must never stand in for approving.

    A run parked on a live permission request is waiting for a decision, not for
    information. Accepting an answer there would let the clarification path
    sidestep the Trust Engine approval the run was stopped for.
    """
    orchestrator = _orchestrator(
        SequenceBrain(AgentDecision.tool_call("calendar.create", {})),
        ConfirmationTool(),
        FakeActionRepository(),
    )
    run = AgentRun(EntityId.new(), "Create an event", user_id=EntityId.new())
    asyncio.run(orchestrator.execute(run, user_id=str(run.user_id)))

    with pytest.raises(ValueError):
        asyncio.run(orchestrator.answer(run, "sí, adelante", user_id=str(run.user_id)))
