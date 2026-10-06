import asyncio

import pytest

from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.firewall import MemoryFirewall
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.memory.service import MemoryService
from app.domain.entities.memory import Memory
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.memory.skill import MemorySkill
from app.infrastructure.skills.memory.tools.delete_memory import MemoryDeleteTool
from app.infrastructure.skills.memory.tools.get_memory import MemoryGetTool
from app.infrastructure.skills.memory.tools.save_memory import MemorySaveTool
from app.infrastructure.skills.memory.tools.search_memory import MemorySearchTool
from tests.unit.application.test_memory_system import FakeMemoryRepository


class ExplodingMemoryRepository(FakeMemoryRepository):
    def search(self, agent_id, user_id, query, limit=10, memory_types=None):
        raise RuntimeError("connection reset by peer")


@pytest.fixture
def repository() -> FakeMemoryRepository:
    return FakeMemoryRepository()


@pytest.fixture
def service(repository: FakeMemoryRepository) -> MemoryService:
    return MemoryService(repository, DeterministicMemoryPolicy(), MemoryFirewall())


@pytest.fixture
def context() -> ToolContext:
    # ``user_id`` is part of the context now, not just the agent. The memory tools
    # scope every read and write to it, so a context without one is refused
    # outright -- see test_memory_tools_refuse_a_context_with_no_identity.
    return ToolContext(
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        user_id=EntityId.new(),
        user_request="Recuerda que mi proyecto usa PostgreSQL",
    )


def memory_owned_by(context: ToolContext, **kwargs) -> Memory:
    """A memory owned by whoever is making the call."""
    return Memory(user_id=context.user_id, **kwargs)


def run(coroutine):
    return asyncio.run(coroutine)


def use_cases(service: MemoryService) -> dict:
    return {
        "search_memories": SearchMemoriesUseCase(service),
        "get_memory": GetMemoryUseCase(service),
        "save_memory": SaveMemoryUseCase(service),
        "delete_memory": DeleteMemoryUseCase(service),
    }


def test_skill_exposes_four_namespaced_tools(service: MemoryService) -> None:
    skill = MemorySkill(**use_cases(service))

    definition = skill.definition()

    assert definition.name == "memory"
    assert [tool.definition().name for tool in skill.tools()] == [
        "memory.search",
        "memory.get",
        "memory.save",
        "memory.delete",
    ]
    assert all(tool.definition().skill_name == "memory" for tool in skill.tools())


def test_tool_metadata_declares_risk(service: MemoryService) -> None:
    tools = {tool.definition().name: tool.definition() for tool in MemorySkill(**use_cases(service)).tools()}

    assert tools["memory.search"].read_only is True
    assert tools["memory.get"].read_only is True
    assert tools["memory.save"].read_only is False
    assert tools["memory.save"].side_effect is True
    # Saving is an internal, reversible, agent-scoped write; MemoryPolicy and
    # MemoryFirewall decide whether it is persisted. Deleting is destructive
    # and stays behind a human approval.
    assert tools["memory.save"].risk_level is RiskLevel.LOW
    assert tools["memory.delete"].risk_level is RiskLevel.MEDIUM


def test_memory_search_finds_memories_of_the_context_agent(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    repository.save(
        memory_owned_by(
            context,
            agent_id=context.agent_id,
            content="The project uses PostgreSQL",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
    )
    repository.save(
        memory_owned_by(
            context,
            agent_id=EntityId.new(),
            content="The project uses PostgreSQL too",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
    )

    result = run(MemorySearchTool(use_cases(service)["search_memories"]).execute({"query": "PostgreSQL"}, context))

    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["items"][0]["content"] == "The project uses PostgreSQL"


def test_memory_search_hides_another_users_memories(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    """Same agent, different owner: search must not surface it.

    Agent scoping alone would pass this test's sibling cases, because the decoy
    above has a different agent too. Sharing an agent is the realistic shape --
    a user with several assistants -- and it is the case a missing owner column
    let through.
    """
    repository.save(
        Memory(
            user_id=EntityId.new(),
            agent_id=context.agent_id,
            content="Another user's PostgreSQL note",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
    )

    result = run(MemorySearchTool(use_cases(service)["search_memories"]).execute({"query": "PostgreSQL"}, context))

    assert result.success is True
    assert result.data["count"] == 0


def test_memory_tools_refuse_a_context_with_no_identity(
    service: MemoryService, repository: FakeMemoryRepository
) -> None:
    """No acting user means no scope, so no memory tool runs.

    ``ToolContext.user_id`` is optional on the dataclass, which makes a
    hand-built context without one easy to produce. Refusing here is what keeps
    the ownership requirement from holding only on orchestrator-driven paths.
    """
    anonymous = ToolContext(
        agent_id=EntityId.new(), agent_run_id=EntityId.new(), user_request="hello"
    )
    tools = {tool.definition().name: tool for tool in MemorySkill(**use_cases(service)).tools()}

    for name, payload in (
        ("memory.search", {"query": "anything"}),
        ("memory.get", {"memory_id": str(EntityId.new())}),
        ("memory.save", {"content": "Prefers Docker", "memory_type": "PREFERENCE"}),
        ("memory.delete", {"memory_id": str(EntityId.new())}),
    ):
        result = run(tools[name].execute(payload, anonymous))

        assert result.success is False, name
        assert result.error_code == ToolErrorCode.FORBIDDEN_ARGUMENTS, name

    assert repository.items == {}


def test_memory_search_rejects_empty_query(service: MemoryService, context: ToolContext) -> None:
    result = run(MemorySearchTool(use_cases(service)["search_memories"]).execute({"query": "   "}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_memory_search_hides_repository_internals(context: ToolContext) -> None:
    service = MemoryService(ExplodingMemoryRepository(), DeterministicMemoryPolicy(), MemoryFirewall())

    result = run(MemorySearchTool(use_cases(service)["search_memories"]).execute({"query": "anything"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "Traceback" not in result.error_message
    assert "reset by peer" not in result.error_message


def test_memory_get_returns_owned_memory(service: MemoryService, repository: FakeMemoryRepository, context: ToolContext) -> None:
    memory = repository.save(
        memory_owned_by(
            context,
            agent_id=context.agent_id,
            content="Prefers Docker",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.USER_EXPLICIT,
        )
    )

    result = run(MemoryGetTool(use_cases(service)["get_memory"]).execute({"memory_id": str(memory.id)}, context))

    assert result.success is True
    assert result.data["memory_id"] == str(memory.id)


def test_memory_get_reports_missing_memory(service: MemoryService, context: ToolContext) -> None:
    result = run(MemoryGetTool(use_cases(service)["get_memory"]).execute({"memory_id": str(EntityId.new())}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.MEMORY_NOT_FOUND


def test_memory_get_cannot_read_another_users_memory(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    """Same agent, different owner. The agent matches, so only ownership stops it.

    The previous version of this test used a memory on a *different agent*, which
    meant it passed for the wrong reason: the service rejected it on the agent
    check and the missing owner column was never exercised at all.
    """
    memory = repository.save(
        Memory(
            user_id=EntityId.new(),
            agent_id=context.agent_id,
            content="Private note",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
    )

    result = run(MemoryGetTool(use_cases(service)["get_memory"]).execute({"memory_id": str(memory.id)}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.MEMORY_NOT_FOUND


def test_memory_get_rejects_malformed_identifier(service: MemoryService, context: ToolContext) -> None:
    result = run(MemoryGetTool(use_cases(service)["get_memory"]).execute({"memory_id": "not-a-uuid"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_memory_save_respects_the_policy_for_explicit_requests(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "The project uses PostgreSQL", "memory_type": "SEMANTIC", "importance": "HIGH"},
            context,
        )
    )

    assert result.success is True
    assert result.data["saved"] is True
    assert result.data["persistence"] == MemoryPersistenceDecision.SAVE.value
    assert result.data["memory_id"]
    assert len(repository.items) == 1


def test_memory_save_is_blocked_when_the_policy_declines(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "short", "memory_type": "SEMANTIC"},
            context,
        )
    )

    assert result.success is True
    assert result.data["saved"] is False
    assert result.data["persistence"] == MemoryPersistenceDecision.DO_NOT_SAVE.value
    assert result.data["reason"]
    assert repository.items == {}


def test_memory_save_never_persists_sensitive_content(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "The api key is sk-1234567890", "memory_type": "SEMANTIC"},
            context,
        )
    )

    assert result.data["saved"] is False
    assert repository.items == {}


def test_memory_save_uses_the_user_request_from_the_trusted_context(
    service: MemoryService, repository: FakeMemoryRepository
) -> None:
    context = ToolContext(
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        user_id=EntityId.new(),
        user_request="Recuerda que mi proyecto usa PostgreSQL",
    )

    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "The project database is PostgreSQL 16", "memory_type": "SEMANTIC"},
            context,
        )
    )

    assert result.data["saved"] is True
    assert len(repository.items) == 1


def test_memory_save_rejects_invalid_arguments(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "The project uses PostgreSQL", "memory_type": "NOT_A_TYPE"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert repository.items == {}


def test_memory_save_reports_the_firewall_when_policy_is_bypassed(context: ToolContext) -> None:
    class LeakyService(MemoryService):
        def save_memory(self, candidate: MemoryCandidate):
            raise ValueError("DO_NOT_SAVE memory cannot reach persistence")

    service = LeakyService(FakeMemoryRepository(), DeterministicMemoryPolicy(), MemoryFirewall())

    result = run(
        MemorySaveTool(use_cases(service)["save_memory"]).execute(
            {"content": "The project uses PostgreSQL", "memory_type": "SEMANTIC"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.MEMORY_BLOCKED
    assert "DO_NOT_SAVE" not in result.error_message


def test_memory_delete_removes_the_memory(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    memory = repository.save(
        memory_owned_by(
            context,
            agent_id=context.agent_id,
            content="Forget this",
            memory_type=MemoryType.EPISODIC,
            source=MemorySource.AGENT_ACTION,
        )
    )

    result = run(MemoryDeleteTool(use_cases(service)["delete_memory"]).execute({"memory_id": str(memory.id)}, context))

    assert result.success is True
    assert result.data["deleted"] is True
    assert repository.items == {}


def test_memory_delete_reports_missing_memory(service: MemoryService, context: ToolContext) -> None:
    result = run(MemoryDeleteTool(use_cases(service)["delete_memory"]).execute({"memory_id": str(EntityId.new())}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.MEMORY_NOT_FOUND


def test_memory_delete_cannot_delete_another_users_memory(
    service: MemoryService, repository: FakeMemoryRepository, context: ToolContext
) -> None:
    """Same agent, different owner: the delete must not happen.

    As with the get case, the earlier version differed only by agent and so was
    really testing the agent check. This one can only pass on ownership.
    """
    memory = repository.save(
        Memory(
            user_id=EntityId.new(),
            agent_id=context.agent_id,
            content="Private",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
    )

    result = run(MemoryDeleteTool(use_cases(service)["delete_memory"]).execute({"memory_id": str(memory.id)}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.MEMORY_NOT_FOUND
    assert memory.id in repository.items


def test_memory_skill_never_calls_the_llm_or_the_orchestrator() -> None:
    import inspect

    for module in (
        "app.infrastructure.skills.memory.tools.search_memory",
        "app.infrastructure.skills.memory.tools.get_memory",
        "app.infrastructure.skills.memory.tools.save_memory",
        "app.infrastructure.skills.memory.tools.delete_memory",
    ):
        source = inspect.getsource(__import__(module, fromlist=["*"])).lower()
        assert "llm" not in source
        assert "orchestrator" not in source
        assert "subprocess" not in source


def test_memory_tools_go_through_the_memory_service(service: MemoryService) -> None:
    use_case = use_cases(service)["save_memory"]

    assert isinstance(use_case, SaveMemoryUseCase)
    assert isinstance(use_case.memory_service, MemoryService)
    assert isinstance(use_case.memory_service.policy, DeterministicMemoryPolicy)
    assert isinstance(use_case.memory_service.firewall, MemoryFirewall)
    assert MemoryImportance.HIGH is not None
