import asyncio

from app.application.agents.context_builder import AgentContextBuilder
from app.application.agents.orchestrator import AgentOrchestrator
from app.application.tools.executor import RegistryToolExecutor
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentBrain, AgentDecision
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.ports.agent_runtime import (
    RuntimePolicyRejectedError,
    RuntimeUnavailableError,
)
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition, ToolResult
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.services.agent_run_state_service import AgentRunStateService
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.security.trust_engine import DeterministicTrustEngine


class FakeRunRepository(AgentRunRepository):
    def __init__(self):
        self.items = {}

    def save(self, run):
        self.items[run.id] = run
        return run

    def get_by_id(self, run_id):
        return self.items.get(run_id)


class FakeActionRepository(AgentActionRepository):
    def __init__(self):
        self.items = []

    def save(self, action):
        self.items.append(action)
        return action

    def list_by_run(self, agent_run_id):
        return [action for action in self.items if action.agent_run_id == agent_run_id]


class FakeTool(Tool):
    def __init__(self, name="task.create", risk=RiskLevel.LOW, confirm=False):
        self.calls = 0
        self._definition = ToolDefinition(name, "Fake tool", {"type": "object"}, "tasks", risk, confirm)

    def definition(self):
        return self._definition

    async def execute(self, arguments, context: ToolContext):
        self.calls += 1
        return ToolResult(True, self._definition.name, {"arguments": arguments})


class SequenceBrain(AgentBrain):
    def __init__(self, *decisions):
        self.decisions = list(decisions)

    async def decide(self, agent_run, context, tool_definitions):
        return self.decisions.pop(0) if self.decisions else AgentDecision.final("done")


class LoopBrain(AgentBrain):
    async def decide(self, agent_run, context, tool_definitions):
        return AgentDecision.tool_call("task.create", {"title": "repeat"})


def make_orchestrator(brain, tool, max_iterations=10):
    registry = InMemoryToolRegistry([tool])
    # Keyword arguments only. The orchestrator takes several same-typed
    # collaborators, and a positional list silently swaps them.
    return AgentOrchestrator(
        agent_brain=brain,
        context_builder=AgentContextBuilder(None, registry),
        tool_registry=registry,
        tool_executor=RegistryToolExecutor(registry),
        trust_engine=DeterministicTrustEngine(),
        agent_run_repository=FakeRunRepository(),
        agent_action_repository=FakeActionRepository(),
        state_service=AgentRunStateService(),
        max_iterations=max_iterations,
    )


def test_orchestrator_can_finish_without_tool() -> None:
    run = AgentRun(EntityId.new(), "Hello NEXUS")
    result = asyncio.run(make_orchestrator(SequenceBrain(AgentDecision.final("Hello")), FakeTool()).execute(run))

    assert result.response == "Hello"
    assert run.status is AgentRunStatus.COMPLETED


def test_orchestrator_executes_tool_then_observes_and_finishes() -> None:
    tool = FakeTool()
    brain = SequenceBrain(AgentDecision.tool_call("task.create", {"title": "Demo"}), AgentDecision.final("Done"))
    run = AgentRun(EntityId.new(), "Create a task")
    result = asyncio.run(make_orchestrator(brain, tool).execute(run))

    assert result.response == "Done"
    assert tool.calls == 1
    assert run.status is AgentRunStatus.COMPLETED


def test_orchestrator_pauses_for_confirmation() -> None:
    tool = FakeTool(confirm=True)
    run = AgentRun(EntityId.new(), "Create an event")
    result = asyncio.run(make_orchestrator(SequenceBrain(AgentDecision.tool_call("task.create", {})), tool).execute(run))

    assert result.question == "Allow task.create?"
    assert run.status is AgentRunStatus.WAITING_PERMISSION
    assert tool.calls == 0


def test_orchestrator_blocks_high_risk_tool() -> None:
    tool = FakeTool(risk=RiskLevel.HIGH)
    run = AgentRun(EntityId.new(), "Read secrets")
    result = asyncio.run(make_orchestrator(SequenceBrain(AgentDecision.tool_call("task.create", {})), tool).execute(run))

    assert result.response == "Action blocked by policy"
    assert run.status is AgentRunStatus.BLOCKED
    assert tool.calls == 0


def test_orchestrator_enforces_iteration_limit() -> None:
    run = AgentRun(EntityId.new(), "Repeat forever")
    result = asyncio.run(make_orchestrator(LoopBrain(), FakeTool(), max_iterations=2).execute(run))

    assert result.response == "Agent iteration limit reached"
    assert run.status is AgentRunStatus.FAILED


class UnavailableExecutor(RegistryToolExecutor):
    """Executor whose sandbox cannot be created."""

    def __init__(self, registry, error):
        super().__init__(registry)
        self.error = error
        self.calls = 0

    async def execute(self, tool_name, arguments, context):
        self.calls += 1
        raise self.error


class RejectingExecutor(UnavailableExecutor):
    pass


def orchestrator_with_executor(executor):
    registry = InMemoryToolRegistry([FakeTool()])
    return AgentOrchestrator(
        agent_brain=SequenceBrain(AgentDecision.tool_call("task.create", {})),
        context_builder=AgentContextBuilder(None, registry),
        tool_registry=registry,
        tool_executor=executor,
        trust_engine=DeterministicTrustEngine(),
        agent_run_repository=FakeRunRepository(),
        agent_action_repository=FakeActionRepository(),
        state_service=AgentRunStateService(),
    )


def test_an_unavailable_runtime_does_not_strand_the_run() -> None:
    # The run is moved to EXECUTING before the tool is invoked, so an exception
    # escaping the executor left it EXECUTING forever with nothing to move it on.
    executor = UnavailableExecutor(
        InMemoryToolRegistry([FakeTool()]),
        RuntimeUnavailableError("gateway refused"),
    )
    orchestrator = orchestrator_with_executor(executor)
    run = AgentRun(EntityId.new(), "Run something sandboxed")

    result = asyncio.run(orchestrator.execute(run))

    assert run.status is AgentRunStatus.FAILED
    assert "Runtime unavailable" in (result.response or "")
    assert executor.calls == 1


def test_a_rejected_policy_does_not_strand_the_run() -> None:
    executor = RejectingExecutor(
        InMemoryToolRegistry([FakeTool()]),
        RuntimePolicyRejectedError("filesystem rules rejected"),
    )
    orchestrator = orchestrator_with_executor(executor)
    run = AgentRun(EntityId.new(), "Run something sandboxed")

    result = asyncio.run(orchestrator.execute(run))

    assert run.status is AgentRunStatus.FAILED
    assert "Runtime unavailable" in (result.response or "")


def test_no_execution_is_retried_on_the_host_after_a_runtime_failure() -> None:
    executor = UnavailableExecutor(
        InMemoryToolRegistry([FakeTool()]),
        RuntimeUnavailableError("gateway refused"),
    )
    orchestrator = orchestrator_with_executor(executor)
    run = AgentRun(EntityId.new(), "Run something sandboxed")

    asyncio.run(orchestrator.execute(run))

    # Exactly one attempt. A retry here would mean running the workload outside
    # the sandbox, which is the one thing this layer exists to prevent.
    assert executor.calls == 1
