from pydantic import Field, model_validator

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.skills.github.client import GitHubClient, OWNER_PATTERN


class ListGitHubReposInput(ToolInput):
    user: str | None = Field(default=None, pattern=OWNER_PATTERN, max_length=39)
    org: str | None = Field(default=None, pattern=OWNER_PATTERN, max_length=39)
    limit: int = Field(default=30, ge=1, le=100)
    page: int = Field(default=1, ge=1, le=1000)

    @model_validator(mode="after")
    def one_owner(self):
        if self.user and self.org:
            raise ValueError("Choose user or org, not both")
        return self


class GitHubRepoOutput(ToolOutput):
    id: str
    name: str
    full_name: str
    description: str | None = None
    html_url: str | None = None
    private: bool = False


class GitHubReposOutput(ToolOutput):
    items: list[GitHubRepoOutput]
    page: int


class ListGitHubReposTool(UseCaseTool):
    def __init__(self, client: GitHubClient | None = None) -> None:
        self.client = client or GitHubClient()
        super().__init__(name="github.list_repos", description="List GitHub repositories. Public user/org listings need no token; omit user/org only with a configured token to list its owner's repositories.", skill_name="github", input_model=ListGitHubReposInput, input_schema=ListGitHubReposInput.model_json_schema(), risk_level=RiskLevel.LOW, read_only=True)

    async def run(self, payload: ListGitHubReposInput, context: ToolContext) -> GitHubReposOutput:
        path = f"/orgs/{payload.org}/repos" if payload.org else f"/users/{payload.user}/repos" if payload.user else "/user/repos"
        data = await self.client.request("GET", path, context, params={"per_page": payload.limit, "page": payload.page, "sort": "updated"})
        return GitHubReposOutput(items=[GitHubRepoOutput(id=str(item["id"]), name=item["name"], full_name=item["full_name"], description=item.get("description"), html_url=item.get("html_url"), private=item.get("private", False)) for item in data], page=payload.page)
