from fastapi.testclient import TestClient

from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.firewall import MemoryFirewall
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.memory.service import MemoryService
from app.application.skills.catalog import SkillAwareToolCatalog
from app.application.skills.registry import SkillRegistry
from app.application.skills.selector import KeywordSkillSelector
from app.application.tools.registry import InMemoryToolRegistry
from app.infrastructure.skills.memory.skill import MemorySkill
from app.infrastructure.skills.tasks.skill import TaskSkill
from app.main import app
from app.presentation.dependencies.agent import SkillSystem, skill_system_dependency
from tests.support.repositories import FakeTaskRepository
from tests.unit.application.test_memory_system import FakeMemoryRepository


def build_skill_system() -> SkillSystem:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    service = MemoryService(FakeMemoryRepository(), DeterministicMemoryPolicy(), MemoryFirewall())
    skills.register(TaskSkill(FakeTaskRepository()))
    skills.register(
        MemorySkill(
            search_memories=SearchMemoriesUseCase(service),
            get_memory=GetMemoryUseCase(service),
            save_memory=SaveMemoryUseCase(service),
            delete_memory=DeleteMemoryUseCase(service),
        )
    )
    selector = KeywordSkillSelector()
    return SkillSystem(
        skills=skills,
        tools=tools,
        catalog=SkillAwareToolCatalog(skills, tools, selector),
        selector=selector,
    )


app.dependency_overrides[skill_system_dependency] = build_skill_system
client = TestClient(app)


def test_skills_endpoint_lists_capabilities_and_their_tools() -> None:
    response = client.get("/api/v1/skills")

    assert response.status_code == 200
    skills = {skill["name"]: skill for skill in response.json()["skills"]}
    assert set(skills) == {"tasks", "memory"}
    assert skills["tasks"]["enabled"] is True
    assert skills["tasks"]["tools"] == [
        "task.create",
        "task.list",
        "task.get",
        "task.update",
        "task.complete",
    ]
    assert skills["memory"]["tools"] == [
        "memory.search",
        "memory.get",
        "memory.save",
        "memory.delete",
    ]


def test_tools_endpoint_exposes_metadata_without_secrets() -> None:
    response = client.get("/api/v1/tools")

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["tools"]}
    assert tools["task.create"]["skill"] == "tasks"
    assert tools["task.create"]["risk_level"] == "LOW"
    assert tools["task.create"]["read_only"] is False
    assert tools["task.create"]["side_effect"] is True
    assert tools["task.list"]["read_only"] is True
    assert tools["memory.save"]["risk_level"] == "LOW"
    assert tools["task.create"]["input_schema"]["required"] == ["title"]
    body = response.text.lower()
    for secret in ("password", "api_key", "secret", "token", "traceback", "select ", "dialect"):
        assert secret not in body


def test_there_is_no_endpoint_to_execute_a_tool_directly() -> None:
    paths = {route.path for route in app.routes}

    assert not any("execute" in path for path in paths)
    assert not any("{tool_name}" in path for path in paths)
