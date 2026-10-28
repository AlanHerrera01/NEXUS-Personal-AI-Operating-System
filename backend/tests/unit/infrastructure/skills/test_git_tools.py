from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.git.tools.diff import GitDiffTool, GitResult


class FakeGitRunner:
    def __init__(self, diff: str = "diff --git a/a.py b/a.py\n+print('hola')\n") -> None:
        self.diff = diff
        self.calls: list[list[str]] = []

    def run(self, args: list[str], *, cwd: Path, timeout: float) -> GitResult:
        self.calls.append(args)
        if "rev-parse" in args:
            return GitResult(0, "true\n", "")
        return GitResult(0, self.diff, "")


def _settings(repo: Path) -> Settings:
    return Settings(_env_file=None, git_repo_path=str(repo), git_max_diff_chars=1_000)


def _context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


async def test_git_diff_runs_only_in_the_configured_repository(tmp_path) -> None:
    runner = FakeGitRunner()
    tool = GitDiffTool(_settings(tmp_path), runner=runner)

    result = await tool.execute({"path": "src/app.py", "staged": True}, _context())

    assert result.success is True
    assert "hola" in result.data["diff"]
    assert result.data["staged"] is True
    assert result.data["path"] == "src/app.py"
    assert result.data["changed"] is True
    assert runner.calls[0] == [
        "git",
        "-c",
        "safe.directory=*",
        "rev-parse",
        "--is-inside-work-tree",
    ]
    assert "--cached" in runner.calls[1]
    assert "--no-ext-diff" in runner.calls[1]
    assert "--no-textconv" in runner.calls[1]
    assert runner.calls[1][-2:] == ["--", "src/app.py"]


async def test_git_diff_rejects_absolute_and_parent_paths(tmp_path) -> None:
    runner = FakeGitRunner()
    tool = GitDiffTool(_settings(tmp_path), runner=runner)

    parent = await tool.execute({"path": "../secrets.txt"}, _context())
    assert parent.success is False
    assert parent.error_code == "GIT_DIFF_FAILED"

    absolute = await tool.execute({"path": str(tmp_path / "a.py")}, _context())
    assert absolute.success is False
    assert absolute.error_code == "GIT_DIFF_FAILED"
    # Each call performs the repository check before validating the path.
    assert len(runner.calls) == 2
    assert all("rev-parse" in call for call in runner.calls)


async def test_git_diff_reports_a_missing_repository(tmp_path) -> None:
    tool = GitDiffTool(_settings(tmp_path / "missing"), runner=FakeGitRunner())

    result = await tool.execute({}, _context())

    assert result.success is False
    assert result.error_code == "GIT_REPOSITORY_NOT_FOUND"


async def test_git_diff_truncates_large_output(tmp_path) -> None:
    runner = FakeGitRunner("x" * 5_000)
    tool = GitDiffTool(
        Settings(_env_file=None, git_repo_path=str(tmp_path), git_max_diff_chars=1_000),
        runner=runner,
    )

    result = await tool.execute({}, _context())

    assert result.success is True
    assert result.data["truncated"] is True
    assert result.data["changed"] is True
