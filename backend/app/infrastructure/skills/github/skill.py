from dataclasses import dataclass

from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.github.tools.create_issue import CreateGitHubIssueTool
from app.infrastructure.skills.github.tools.create_pull_request import CreateGitHubPRTool
from app.infrastructure.skills.github.tools.list_repos import ListGitHubReposTool
from app.infrastructure.skills.github.tools.contracts import SKILL_NAME


@dataclass
class GitHubSkill(Skill):
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Interact with GitHub repositories and workflows.",
            version="1.0.0",
            enabled=True,
            category="development",
            keywords=("github", "repositorio", "repo", "git", "commit", "push", "pull request"),
        )

    def tools(self) -> list[Tool]:
        return [
            ListGitHubReposTool(),
            CreateGitHubIssueTool(),
            CreateGitHubPRTool(),
        ]