from datetime import datetime

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput


class ListGitHubReposInput(ToolInput):
    user: str | None = None
    org: str | None = None


class GitHubRepoOutput(ToolOutput):
    id: str
    name: str
    full_name: str
    description: str | None = None
    html_url: str | None = None
    private: bool = False


class ListGitHubReposTool(UseCaseTool):
    """Lista repositorios de GitHub - SIMULATION MODE.

    En modo simulation, devuelve repositorios de ejemplo del usuario.
    En producción real, conectaría con la API de GitHub.
    """

    def __init__(self) -> None:
        super().__init__(
            name="github.list_repos",
            description="List GitHub repositories for a user or organization",
            skill_name="github",
            input_model=ListGitHubReposInput,
            input_schema=ListGitHubReposInput.model_json_schema(),
            risk_level="LOW",
            read_only=True,
            side_effect=False,
            requires_confirmation=False,
        )

    async def run(self, payload: ListGitHubReposInput) -> list[GitHubRepoOutput]:
        # SIMULATION: Devolver repositorios de ejemplo
        # Usar el usuario por defecto o el especificado
        user = payload.user or "nexus-ai"
        org = payload.org or None

        # Repositorios de ejemplo
        repos = [
            GitHubRepoOutput(
                id="1",
                name="nexus-os",
                full_name=f"{user}/nexus-os",
                description="Personal AI Operating System - Hackathon 2026",
                html_url=f"https://github.com/{user}/nexus-os",
                private=False,
            ),
            GitHubRepoOutput(
                id="2",
                name="examples",
                full_name=f"{user}/examples",
                description="Example projects and configurations",
                html_url=f"https://github.com/{user}/examples",
                private=False,
            ),
            GitHubRepoOutput(
                id="3",
                name="docs",
                full_name=f"{user}/docs",
                description="Documentation and DEVPOST materials",
                html_url=f"https://github.com/{user}/docs",
                private=False,
            ),
        ]

        # Filtrar por organización si se especifica
        if org:
            repos = [r for r in repos if r.full_name.startswith(f"{org}/")]

        return repos