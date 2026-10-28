from dataclasses import dataclass

from app.application.knowledge.ingest_knowledge import IngestKnowledgeUseCase
from app.application.knowledge.search_knowledge import SearchKnowledgeUseCase
from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.domain.repositories.knowledge_repository import KnowledgeRepository
from app.infrastructure.documents import Workspace
from app.infrastructure.skills.knowledge.tools.contracts import SKILL_NAME
from app.infrastructure.skills.knowledge.tools.ingest import KnowledgeIngestTool
from app.infrastructure.skills.knowledge.tools.search import KnowledgeSearchTool

KEYWORDS = (
    "conocimiento",
    "knowledge",
    "rag",
    "base de conocimiento",
    "apunte",
    "apuntes",
    "indexar",
    "ingest",
    "ingesta",
    "documento",
    "documentos",
    "manual",
    "nota",
    "notas",
)


@dataclass
class KnowledgeSkill(Skill):
    repository: KnowledgeRepository
    settings: Settings

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description=(
                "Store documents and notes locally, chunk them, and retrieve "
                "relevant passages by keyword."
            ),
            version="1.0.0",
            enabled=True,
            category="knowledge",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        workspace = Workspace(self.settings.files_workspace_root)
        return [
            KnowledgeIngestTool(
                IngestKnowledgeUseCase(self.repository), workspace, self.settings
            ),
            KnowledgeSearchTool(SearchKnowledgeUseCase(self.repository)),
        ]
