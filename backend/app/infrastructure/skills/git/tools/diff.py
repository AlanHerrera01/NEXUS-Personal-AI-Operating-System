"""``git.diff``: read the local working-tree diff through a bounded runner.

No refs, no revision ranges and no shell are accepted from the model. The only
choices are a path relative to the configured repository and whether to show
the staged diff. External diff drivers and textconv filters are disabled so a
repository cannot turn ``git diff`` into execution of its own program.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import Field

from app.application.security.injection import fence
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.git.tools.contracts import SKILL_NAME, GitDiffOutput

MAX_PATH_LENGTH = 1_000


@dataclass(frozen=True, slots=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner(Protocol):
    def run(self, args: list[str], *, cwd: Path, timeout: float) -> GitResult: ...


class SubprocessGitRunner:
    def run(self, args: list[str], *, cwd: Path, timeout: float) -> GitResult:
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_EXTERNAL_DIFF": "",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C.UTF-8",
            }
        )
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return GitResult(returncode=124, stdout="", stderr="git timed out")
        except OSError as error:
            return GitResult(returncode=127, stdout="", stderr=str(error))
        return GitResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": ["string", "null"],
            "maxLength": MAX_PATH_LENGTH,
            "description": "Optional path relative to the repository root",
        },
        "staged": {
            "type": "boolean",
            "description": "Show the staged diff instead of the working tree",
        },
    },
    "required": [],
    "additionalProperties": False,
}


class GitDiffInput(ToolInput):
    path: str | None = Field(default=None, max_length=MAX_PATH_LENGTH)
    staged: bool = False


class GitDiffTool(UseCaseTool):
    def __init__(
        self,
        settings: Settings,
        *,
        runner: GitRunner | None = None,
    ) -> None:
        super().__init__(
            name="git.diff",
            description=(
                "Read a local git diff from the configured read-only repository. "
                "Optionally restrict it to one relative path or show staged changes."
            ),
            skill_name=SKILL_NAME,
            input_model=GitDiffInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="git",
        )
        self.settings = settings
        self.runner: GitRunner = runner or SubprocessGitRunner()

    async def run(self, payload: GitDiffInput, context: ToolContext) -> GitDiffOutput:
        repo = Path(self.settings.git_repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise ToolExecutionError(
                ToolErrorCode.GIT_REPOSITORY_NOT_FOUND,
                f"git repository path does not exist: {repo}",
            )

        check = await asyncio.to_thread(
            self.runner.run,
            ["git", "-c", "safe.directory=*", "rev-parse", "--is-inside-work-tree"],
            cwd=repo,
            timeout=self.settings.git_timeout_seconds,
        )
        if check.returncode != 0 or check.stdout.strip() != "true":
            raise ToolExecutionError(
                ToolErrorCode.GIT_REPOSITORY_NOT_FOUND,
                "the configured path is not a git working tree",
            )

        relative_path: str | None = None
        if payload.path:
            raw = payload.path.strip()
            candidate = Path(raw)
            if candidate.is_absolute() or candidate.drive or any(
                part == ".." for part in candidate.parts
            ):
                raise ToolExecutionError(
                    ToolErrorCode.GIT_DIFF_FAILED,
                    "the path must be relative and must not leave the repository",
                )
            resolved = (repo / candidate).resolve()
            if resolved != repo and repo not in resolved.parents:
                raise ToolExecutionError(
                    ToolErrorCode.GIT_DIFF_FAILED,
                    "the path must stay inside the repository",
                )
            relative_path = resolved.relative_to(repo).as_posix()
            if not relative_path:
                relative_path = None

        args = [
            "git",
            "-c",
            "safe.directory=*",
            "--no-pager",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
        ]
        if payload.staged:
            args.append("--cached")
        if relative_path:
            args.extend(["--", relative_path])

        result = await asyncio.to_thread(
            self.runner.run,
            args,
            cwd=repo,
            timeout=self.settings.git_timeout_seconds,
        )
        if result.returncode != 0:
            detail = result.stderr.strip()[:1_000] or "git diff failed"
            raise ToolExecutionError(ToolErrorCode.GIT_DIFF_FAILED, detail)

        diff = result.stdout
        truncated = len(diff) > self.settings.git_max_diff_chars
        if truncated:
            diff = diff[: self.settings.git_max_diff_chars]

        return GitDiffOutput(
            repo=str(repo),
            path=relative_path,
            staged=payload.staged,
            diff=fence(
                diff,
                source=f"git.diff {relative_path or 'repository'}",
                max_chars=self.settings.git_max_diff_chars,
            ),
            changed=bool(result.stdout.strip()),
            truncated=truncated,
            fetched_at=datetime.now(UTC),
        )
