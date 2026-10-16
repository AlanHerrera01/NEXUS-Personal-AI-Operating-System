from datetime import datetime

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput


class CreateGitHubPRInput(ToolInput):
    title: str
    body: str | None = None
    head: str
    base: str


class CreateGitHubPROutput(ToolOutput):
    pr_number: int
    title: str
    html_url: str | None = None
    state: str = "open"


class CreateGitHubPRTool(UseCaseTool):
    """Crea una pull request en GitHub - SIMULATION MODE.

    En modo simulation, crea una PR con número consecutivo.
    El requires_confirmation=True significa que siempre pausará para
    aprobación humana antes de crear la PR.
    """

    def __init__(self) -> None:
        super().__init__(
            name="github.create_pull_request",
            description="Create a GitHub pull request",
            skill_name="github",
            input_model=CreateGitHubPRInput,
            input_schema=CreateGitHubPRInput.model_json_schema(),
            risk_level="LOW",
            read_only=False,
            side_effect=True,
            requires_confirmation=True,
        )

    async def run(self, payload: CreateGitHubPRInput, context: object) -> CreateGitHubPROutput:
        # SIMULATION: Crear una PR con número basado en el título
        import hashlib
        number = int(hashlib.md5(payload.title.encode()).hexdigest()[:6], 16) % 1000 + 1

        # Generar URL simulada
        url = f"https://github.com/pull/{number}"

        return CreateGitHubPROutput(
            pr_number=number,
            title=payload.title,
            html_url=url,
            state="open",
        )