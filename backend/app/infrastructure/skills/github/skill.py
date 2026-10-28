from dataclasses import dataclass

from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.github.tools.create_issue import CreateGitHubIssueTool
from app.infrastructure.skills.github.tools.create_pull_request import CreateGitHubPRTool
from app.infrastructure.skills.github.tools.list_repos import ListGitHubReposTool
from app.infrastructure.skills.github.tools.contracts import SKILL_NAME
from app.config.settings import Settings
from app.infrastructure.skills.github.client import GitHubClient
from app.infrastructure.skills.github.tools.read_repository import GetGitHubRepositoryTool, ReadGitHubContentsTool


@dataclass
class GitHubSkill(Skill):
    settings: Settings | None = None

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
        client = GitHubClient(self.settings)
        return [
            ListGitHubReposTool(client),
            GetGitHubRepositoryTool(client),
            ReadGitHubContentsTool(client),
            CreateGitHubIssueTool(client),
            CreateGitHubPRTool(client),
        ]
