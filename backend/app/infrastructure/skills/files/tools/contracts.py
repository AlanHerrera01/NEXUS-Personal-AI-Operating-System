from datetime import datetime
from typing import Any

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "files"


class FileSearchItem(ToolOutput):
    path: str
    name: str
    size: int
    modified_at: datetime
    match: str
    snippet: str = ""


class FileSearchOutput(ToolOutput):
    query: str
    items: list[FileSearchItem]
    count: int
    scanned: int
    truncated: bool = False


class FileReadOutput(ToolOutput):
    path: str
    content: str
    size: int
    modified_at: datetime
    truncated: bool = False


class DocumentExtractOutput(ToolOutput):
    path: str
    format: str
    content: str
    size: int
    modified_at: datetime
    truncated: bool = False
    metadata: dict[str, Any]
