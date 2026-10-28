from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.git.tools.contracts import SKILL_NAME
from app.infrastructure.skills.git.tools.diff import GitDiffTool

KEYWORDS = (
    "git",
    "diff",
    "cambios",
    "cambio",
    "modificaciones",
    "repositorio",
    "repo",
    "commit",
)


@dataclass
class GitSkill(Skill):
    settings: Settings

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Read local git diffs without executing repository hooks.",
            version="1.0.0",
            enabled=True,
            category="git",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [GitDiffTool(self.settings)]
