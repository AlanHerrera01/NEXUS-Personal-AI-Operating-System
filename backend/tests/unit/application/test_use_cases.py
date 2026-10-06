from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.application.agents.create_agent import CreateAgentUseCase
from app.application.execution_plans.add_plan_step import AddPlanStepUseCase
from app.application.execution_plans.create_execution_plan import CreateExecutionPlanUseCase
from app.domain.entities.agent import Agent
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.entities.plan_step import PlanStep
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.execution_plan_repository import ExecutionPlanRepository
from app.domain.value_objects.entity_id import EntityId


class FakeAgentRepository(AgentRepository):
    def __init__(self) -> None:
        self.items: dict[EntityId, Agent] = {}

    def save(self, agent: Agent) -> Agent:
        self.items[agent.id] = agent
        return agent

    def get_by_id(self, agent_id: EntityId, user_id: EntityId) -> Agent | None:
        agent = self.items.get(agent_id)
        if agent is None or agent.user_id != user_id:
            return None
        return agent


class FakeAgentRunRepository(AgentRunRepository):
    def __init__(self) -> None:
        self.items: dict[EntityId, AgentRun] = {}

    def save(self, agent_run: AgentRun) -> AgentRun:
        self.items[agent_run.id] = agent_run
        return agent_run

    def get_by_id(self, agent_run_id: EntityId, user_id: EntityId) -> AgentRun | None:
        run = self.items.get(agent_run_id)
        if run is None or run.user_id != user_id:
            return None
        return run


class FakeExecutionPlanRepository(ExecutionPlanRepository):
    def __init__(self) -> None:
        self.items: dict[EntityId, ExecutionPlan] = {}

    def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        self.items[plan.id] = plan
        return plan

    def get_by_id(self, plan_id: EntityId) -> ExecutionPlan | None:
        return self.items.get(plan_id)


def test_use_cases_compose_through_repository_ports() -> None:
    agents = FakeAgentRepository()
    runs = FakeAgentRunRepository()
    plans = FakeExecutionPlanRepository()
    user = EntityId.new()

    agent = CreateAgentUseCase(agents).execute("NEXUS", user, "Personal AI")
    run = CreateAgentRunUseCase(agents, runs).execute(agent.id, "Prepare my day", user)
    plan = CreateExecutionPlanUseCase(runs, plans).execute(run.id, user)
    updated = AddPlanStepUseCase(plans).execute(plan.id, PlanStep(1, "tasks", "list"))

    assert updated.agent_run_id == run.id
    assert updated.steps[0].skill_name == "tasks"
    # Ownership propagates end to end rather than being dropped at each hop.
    assert agent.user_id == user
    assert run.user_id == user


def test_run_creation_rejects_missing_agent() -> None:
    agents = FakeAgentRepository()
    runs = FakeAgentRunRepository()

    try:
        CreateAgentRunUseCase(agents, runs).execute(
            EntityId.new(), "Hello", EntityId.new()
        )
    except ValueError as error:
        assert str(error) == "agent not found"
    else:
        raise AssertionError("missing agent should be rejected")


def test_another_users_agent_is_indistinguishable_from_a_missing_one() -> None:
    """"agent not found" must not become "that agent belongs to someone else".

    A distinct error for the second case confirms the agent exists, which turns
    the create-run endpoint into an oracle for enumerating agent ids.
    """
    agents = FakeAgentRepository()
    runs = FakeAgentRunRepository()
    owner = EntityId.new()
    agent = CreateAgentUseCase(agents).execute("NEXUS", owner)

    try:
        CreateAgentRunUseCase(agents, runs).execute(
            agent.id, "Hello", EntityId.new()
        )
    except ValueError as error:
        assert str(error) == "agent not found"
    else:
        raise AssertionError("another user's agent should be rejected")
