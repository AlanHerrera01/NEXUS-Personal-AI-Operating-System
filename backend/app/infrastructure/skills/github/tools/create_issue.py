from datetime import datetime

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput


class CreateGitHubIssueInput(ToolInput):
    title: str
    body: str | None = None
    labels: list[str] | None = None


class CreateGitHubIssueOutput(ToolOutput):
    issue_number: int
    title: str
    html_url: str | None = None
    state: str = "open"


class CreateGitHubIssueTool(UseCaseTool):
    """Crea un issue en GitHub - SIMULATION MODE.

    En modo simulation, crea un issue con número consecutivo y devuelve
    una URL simulada. En producción real, conectaría con la API de GitHub.
    El requiere_confirmation=True significa que siempre pausará para
    aprobación humana antes de crear el issue.
    """

    def __init__(self) -> None:
        super().__init__(
            name="github.create_issue",
            description="Create a GitHub issue",
            skill_name="github",
            input_model=CreateGitHubIssueInput,
            input_schema=CreateGitHubIssueInput.model_json_schema(),
            risk_level="LOW",
            read_only=False,
            side_effect=True,
            requires_confirmation=True,
        )

    async def run(self, payload: CreateGitHubIssueInput, context: object) -> CreateGitHubIssueOutput:
        # SIMULATION: Crear un issue con número basado en el título
        import hashlib
        number = int(hashlib.md5(payload.title.encode()).hexdigest()[:6], 16) % 1000 + 1

        # Generar URL simulada
        url = f"https://github.com/issue/{number}_{payload.title.lower().replace(' ', '-')}"

        return CreateGitHubIssueOutput(
            issue_number=number,
            title=payload.title,
            html_url=url,
            state="open",
        )