import httpx
import pytest

from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.github.client import GitHubClient
from app.infrastructure.skills.github.tools.create_issue import CreateGitHubIssueTool
from app.infrastructure.skills.github.tools.create_pull_request import CreateGitHubPRTool
from app.infrastructure.skills.github.tools.list_repos import ListGitHubReposTool
from app.infrastructure.skills.github.tools.read_repository import GetGitHubRepositoryTool, ReadGitHubContentsTool

CONTEXT = ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new(), user_id=EntityId.new())


def client(handler, **overrides):
    return GitHubClient(Settings(_env_file=None, github_personal_access_token="private-test-token", **overrides), transport=httpx.MockTransport(handler))


async def test_repo_list_calls_authenticated_github_and_returns_real_response():
    def handler(request):
        assert request.url.path == "/user/repos"
        assert request.headers["Authorization"] == "Bearer private-test-token"
        assert request.url.params["per_page"] == "10"
        return httpx.Response(200, json=[{"id": 52, "name": "actual", "full_name": "owner/actual", "private": True}])
    result = await ListGitHubReposTool(client(handler)).execute({"limit": 10}, CONTEXT)
    assert result.success
    assert result.data["items"][0]["id"] == "52"
    assert result.data["items"][0]["private"] is True


@pytest.mark.parametrize("tool_type,path,arguments,number_field", [
    (CreateGitHubIssueTool, "/repos/owner/repo/issues", {"title": "Issue", "labels": ["bug"]}, "issue_number"),
    (CreateGitHubPRTool, "/repos/owner/repo/pulls", {"title": "PR", "head": "feature", "base": "main"}, "pr_number"),
])
async def test_writes_call_real_endpoints_and_keep_human_confirmation(tool_type, path, arguments, number_field):
    def handler(request):
        import json
        assert request.method == "POST"
        assert request.url.path == path
        assert "repository" not in json.loads(request.content)
        return httpx.Response(201, json={"number": 9876, "title": arguments["title"], "state": "open", "html_url": "https://github.com/owner/repo"})
    tool = tool_type(client(handler, github_default_repository="owner/repo"))
    assert tool.definition().requires_confirmation
    assert tool.definition().side_effect
    result = await tool.execute(arguments, CONTEXT)
    assert result.success
    assert result.data[number_field] == 9876


async def test_no_credentials_never_returns_simulated_success():
    result = await ListGitHubReposTool(GitHubClient(Settings(_env_file=None))).execute({}, CONTEXT)
    assert not result.success
    assert result.error_code == "GITHUB_NOT_CONFIGURED"


@pytest.mark.parametrize("arguments,path", [({"user": "octocat"}, "/users/octocat/repos"), ({"org": "github"}, "/orgs/github/repos")])
async def test_public_list_needs_no_token(arguments, path):
    def handler(request):
        assert request.url.path == path
        assert "authorization" not in request.headers
        return httpx.Response(200, json=[])
    public_client = GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    result = await ListGitHubReposTool(public_client).execute(arguments, CONTEXT)
    assert result.success
    assert result.data["items"] == []


async def test_public_repository_can_be_inspected_without_credentials():
    import base64
    calls = []
    def handler(request):
        calls.append(request)
        assert "authorization" not in request.headers
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(200, json={"full_name": "octocat/Hello-World", "default_branch": "main", "language": "Python", "private": False, "html_url": "https://github.com/octocat/Hello-World"})
        if request.url.path.endswith("/contents"):
            return httpx.Response(200, json=[{"type": "file", "path": "README.md"}])
        assert request.url.path.endswith("/contents/README.md")
        assert request.url.params["ref"] == "main"
        return httpx.Response(200, json={"type": "file", "encoding": "base64", "content": base64.b64encode(b"# Actual repository source").decode(), "size": 26})
    public_client = GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    metadata = await GetGitHubRepositoryTool(public_client).execute({"repository": "octocat/Hello-World"}, CONTEXT)
    listing = await ReadGitHubContentsTool(public_client).execute({"repository": "octocat/Hello-World"}, CONTEXT)
    contents = await ReadGitHubContentsTool(public_client).execute({"repository": "octocat/Hello-World", "path": "README.md", "ref": "main"}, CONTEXT)
    assert metadata.success and metadata.data["default_branch"] == "main"
    assert listing.success and listing.data["entries"][0]["path"] == "README.md"
    assert contents.success and contents.data["text"] == "# Actual repository source"
    assert len(calls) == 3


@pytest.mark.parametrize("tool_type,arguments", [(CreateGitHubIssueTool, {"title": "issue", "repository": "octocat/Hello-World"}), (CreateGitHubPRTool, {"title": "pr", "repository": "octocat/Hello-World", "head": "feature", "base": "main"})])
async def test_public_repositories_do_not_allow_unauthenticated_writes(tool_type, arguments):
    def handler(_request):
        pytest.fail("writes must fail before networking without a token")
    result = await tool_type(GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))).execute(arguments, CONTEXT)
    assert not result.success
    assert result.error_code == "GITHUB_NOT_CONFIGURED"


async def test_public_rate_limit_is_an_explicit_error():
    public_client = GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(lambda _: httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})))
    result = await GetGitHubRepositoryTool(public_client).execute({"repository": "octocat/Hello-World"}, CONTEXT)
    assert not result.success
    assert result.error_code == "GITHUB_RATE_LIMITED"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "src/../../secret", "src\\secret"])
async def test_contents_rejects_traversal_before_networking(path):
    def handler(_request):
        pytest.fail("invalid paths cannot make requests")
    public_client = GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    result = await ReadGitHubContentsTool(public_client).execute({"repository": "owner/repo", "path": path}, CONTEXT)
    assert not result.success
    assert result.error_code == "INVALID_ARGUMENTS"


@pytest.mark.parametrize("body,expected", [
    ({"type": "symlink", "target": "https://evil.test"}, "GITHUB_UNSUPPORTED_CONTENT"),
    ({"type": "file", "encoding": "base64", "content": "not base64!", "size": 5}, "GITHUB_UNSUPPORTED_CONTENT"),
    ({"type": "file", "encoding": "base64", "content": "AA==", "size": 1}, "GITHUB_UNSUPPORTED_CONTENT"),
    ({"type": "file", "encoding": "base64", "content": "", "size": 300000}, "GITHUB_FILE_TOO_LARGE"),
])
async def test_unsupported_or_oversized_files_are_refused(body, expected):
    public_client = GitHubClient(Settings(_env_file=None), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    result = await ReadGitHubContentsTool(public_client).execute({"repository": "owner/repo", "path": "file"}, CONTEXT)
    assert not result.success
    assert result.error_code == expected


async def test_provider_errors_are_safe_and_writes_are_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="private-test-token secret provider response")
    result = await CreateGitHubIssueTool(client(handler)).execute({"title": "x", "repository": "owner/repo"}, CONTEXT)
    assert not result.success
    assert result.error_code == "GITHUB_API_ERROR"
    assert "private-test-token" not in result.error_message
    assert len(calls) == 1


@pytest.mark.parametrize("repository", ["../repo", "owner/..", "https://evil.test/repo", "owner/repo/../../x"])
async def test_repository_cannot_redirect_credentials(repository):
    def handler(_request):
        pytest.fail("invalid repository must never make a request")
    result = await CreateGitHubIssueTool(client(handler)).execute({"title": "x", "repository": repository}, CONTEXT)
    assert not result.success
