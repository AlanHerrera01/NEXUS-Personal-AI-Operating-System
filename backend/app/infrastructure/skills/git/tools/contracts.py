from datetime import datetime

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "git"


class GitDiffOutput(ToolOutput):
    repo: str
    path: str | None
    staged: bool
    diff: str
    changed: bool
    truncated: bool
    fetched_at: datetime
