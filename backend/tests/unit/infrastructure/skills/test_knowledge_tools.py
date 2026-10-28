from __future__ import annotations

from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.knowledge.skill import KnowledgeSkill
from tests.support.repositories import FakeKnowledgeRepository


def _settings(root) -> Settings:
    return Settings(
        _env_file=None,
        files_workspace_root=str(root),
        knowledge_chunk_chars=500,
        knowledge_chunk_overlap=50,
    )


def _tools(repository, settings) -> dict[str, object]:
    return {
        tool.definition().name: tool
        for tool in KnowledgeSkill(repository, settings).tools()
    }


def _context(user_id: EntityId | None = None) -> ToolContext:
    return ToolContext(
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        user_id=user_id,
    )


def test_knowledge_skill_exposes_ingest_and_search(tmp_path) -> None:
    tools = _tools(FakeKnowledgeRepository(), _settings(tmp_path))

    assert set(tools) == {"knowledge.ingest", "knowledge.search"}
    ingest = tools["knowledge.ingest"].definition()
    search = tools["knowledge.search"].definition()
    assert ingest.side_effect is True
    assert ingest.read_only is False
    assert search.read_only is True
    assert search.side_effect is False


async def test_ingest_is_idempotent_and_replaceable(tmp_path) -> None:
    repository = FakeKnowledgeRepository()
    tools = _tools(repository, _settings(tmp_path))
    context = _context()

    first = await tools["knowledge.ingest"].execute(
        {"text": "NEXUS usa un motor de permisos.\n" * 80, "title": "Diseño"},
        context,
    )
    assert first.success is True
    assert first.data["created"] is True
    assert first.data["chunks"] > 1

    same = await tools["knowledge.ingest"].execute(
        {"text": "NEXUS usa un motor de permisos.\n" * 80, "title": "Diseño"},
        context,
    )
    assert same.success is True
    assert same.data["created"] is False
    assert same.data["chunks"] == first.data["chunks"]

    changed = await tools["knowledge.ingest"].execute(
        {"text": "NEXUS usa un motor de permisos y auditoría.\n" * 80, "title": "Diseño"},
        context,
    )
    assert changed.success is True
    assert changed.data["created"] is True
    assert changed.data["document_hash"] != first.data["document_hash"]


async def test_search_returns_ranked_chunks_and_respects_owner_scope(tmp_path) -> None:
    repository = FakeKnowledgeRepository()
    tools = _tools(repository, _settings(tmp_path))
    alice = EntityId.new()
    bob = EntityId.new()
    agent = EntityId.new()

    def context(user_id: EntityId) -> ToolContext:
        return ToolContext(
            agent_id=agent,
            agent_run_id=EntityId.new(),
            user_id=user_id,
        )

    ingested = await tools["knowledge.ingest"].execute(
        {
            "text": "El protocolo de emergencia exige avisar al equipo de guardia.",
            "title": "Protocolo",
        },
        context(alice),
    )
    assert ingested.success is True

    found = await tools["knowledge.search"].execute(
        {"query": "protocolo emergencia"}, context(alice)
    )
    assert found.success is True
    assert found.data["count"] == 1
    assert found.data["items"][0]["title"] == "Protocolo"
    assert "guardia" in found.data["items"][0]["content"]

    missing = await tools["knowledge.search"].execute(
        {"query": "protocolo emergencia"}, context(bob)
    )
    assert missing.success is True
    assert missing.data["count"] == 0


async def test_ingest_accepts_a_workspace_file_and_rejects_ambiguous_input(tmp_path) -> None:
    (tmp_path / "runbook.md").write_text(
        "Reiniciar el backend y revisar los logs del contenedor.", encoding="utf-8"
    )
    tools = _tools(FakeKnowledgeRepository(), _settings(tmp_path))
    context = _context()

    from_file = await tools["knowledge.ingest"].execute(
        {"path": "runbook.md"}, context
    )
    assert from_file.success is True
    assert from_file.data["source"] == "runbook.md"
    assert from_file.data["title"] == "runbook.md"

    ambiguous = await tools["knowledge.ingest"].execute(
        {"path": "runbook.md", "text": "también esto"}, context
    )
    assert ambiguous.success is False
    assert ambiguous.error_code == "INVALID_ARGUMENTS"

    empty = await tools["knowledge.search"].execute({"query": "   "}, context)
    assert empty.success is False
    assert empty.error_code == "INVALID_ARGUMENTS"
