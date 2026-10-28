from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.documents import Workspace
from app.infrastructure.skills.files.tools.contracts import SKILL_NAME
from app.infrastructure.skills.files.tools.extract import DocumentExtractTool
from app.infrastructure.skills.files.tools.read import FileReadTool
from app.infrastructure.skills.files.tools.search import FileSearchTool

KEYWORDS = (
    "archivo",
    "archivos",
    "file",
    "files",
    "carpeta",
    "workspace",
    "pdf",
    "docx",
    "xlsx",
    "planilla",
    "spreadsheet",
    "documento",
    "documentos",
    "leer archivo",
    "buscar archivo",
    "extraer texto",
)


@dataclass
class FilesSkill(Skill):
    """Read-only access to a deliberately narrow workspace directory."""

    settings: Settings

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Search, read and extract text from files in the workspace.",
            version="1.0.0",
            enabled=True,
            category="files",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        # Compose mounts the workspace read-only. Creating it here would be a
        # side effect at registration time and would fail on that mount, so the
        # directory is simply expected to exist; a missing one produces a clear
        # "file not found" at call time.
        workspace = Workspace(self.settings.files_workspace_root)
        return [
            FileSearchTool(workspace, self.settings),
            FileReadTool(workspace, self.settings),
            DocumentExtractTool(workspace, self.settings),
        ]
