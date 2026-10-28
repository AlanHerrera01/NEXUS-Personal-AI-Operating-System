from pydantic import Field

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.skills.github.client import GitHubClient, REPOSITORY_PATTERN


class CreateGitHubIssueInput(ToolInput):
    repository: str | None = Field(default=None, pattern="^" + REPOSITORY_PATTERN + "$", max_length=200)
    title: str = Field(min_length=1, max_length=256)
    body: str | None = Field(default=None, max_length=60000)
    labels: list[str] | None = Field(default=None, max_length=50)


class CreateGitHubIssueOutput(ToolOutput):
    issue_number: int
    title: str
    html_url: str | None = None
    state: str = "open"


class CreateGitHubIssueTool(UseCaseTool):
    def __init__(self, client: GitHubClient | None = None) -> None:
        self.client = client or GitHubClient()
        super().__init__(name="github.create_issue", description="Create a real GitHub issue in repository owner/repo.", skill_name="github", input_model=CreateGitHubIssueInput, input_schema=CreateGitHubIssueInput.model_json_schema(), risk_level=RiskLevel.MEDIUM, side_effect=True, requires_confirmation=True)

    async def run(self, payload: CreateGitHubIssueInput, context: ToolContext) -> CreateGitHubIssueOutput:
        repository = self.client.repository(payload.repository)
        data = await self.client.request("POST", f"/repos/{repository}/issues", context, payload=payload.model_dump(exclude={"repository"}, exclude_none=True))
        return CreateGitHubIssueOutput(issue_number=data["number"], title=data["title"], html_url=data.get("html_url"), state=data["state"])
