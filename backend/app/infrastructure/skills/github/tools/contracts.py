from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput
from app.domain.value_objects.entity_id import EntityId

SKILL_NAME = "github"


class GitHubRepositorySummary(ToolOutput):
    repo_id: str
    name: str
    full_name: str
    description: str | None = None
    private: bool = False
    html_url: str | None = None


class GitHubIssueSummary(ToolOutput):
    issue_number: int
    title: str
    body: str | None = None
    state: str = "open"
    html_url: str | None = None


class GitHubPullRequestSummary(ToolOutput):
    pr_number: int
    title: str
    body: str | None = None
    state: str = "open"
    html_url: str | None = None


def require_acting_user(context: object) -> str:
    """Placeholder: GitHub tools will require user authentication context."""
    return "authenticated_user"