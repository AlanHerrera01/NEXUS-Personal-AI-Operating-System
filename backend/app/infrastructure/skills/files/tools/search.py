"""``files.search``: find files by name or text content inside the workspace."""

from __future__ import annotations

from pydantic import Field

from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.documents import (
    Workspace,
    WorkspaceError,
    WorkspaceNotFound,
    WorkspaceUnsupported,
    read_text_file,
)
from app.infrastructure.skills.files.tools.contracts import (
    SKILL_NAME,
    FileSearchItem,
    FileSearchOutput,
)

MAX_QUERY_LENGTH = 500
MAX_LIMIT = 50
MAX_EXTENSIONS = 20

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUERY_LENGTH,
            "description": "Name or text to look for",
        },
        "path": {
            "type": ["string", "null"],
            "maxLength": 1_000,
            "description": "Optional subdirectory inside the workspace",
        },
        "extensions": {
            "type": ["array", "null"],
            "items": {"type": "string", "maxLength": 20},
            "maxItems": MAX_EXTENSIONS,
            "description": "Optional extensions such as .md or .pdf",
        },
        "include_content": {
            "type": "boolean",
            "description": "Also search the text of text-like files",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": "Maximum matches to return",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class FileSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    path: str | None = Field(default=None, max_length=1_000)
    extensions: list[str] | None = Field(default=None, max_length=MAX_EXTENSIONS)
    include_content: bool = True
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)


class FileSearchTool(UseCaseTool[FileSearchInput, FileSearchOutput]):
    def __init__(self, workspace: Workspace, settings: Settings) -> None:
        super().__init__(
            name="files.search",
            description=(
                "Search files inside the configured workspace by name or text "
                "content. Credential-like files are excluded."
            ),
            skill_name=SKILL_NAME,
            input_model=FileSearchInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="files",
        )
        self.workspace = workspace
        self.settings = settings

    async def run(
        self, payload: FileSearchInput, context: ToolContext
    ) -> FileSearchOutput:
        query = payload.query.strip()
        lowered = query.lower()
        wanted = _extensions(payload.extensions)
        limit = min(payload.limit, self.settings.files_max_search_results)
        items: list[FileSearchItem] = []
        scanned = 0
        truncated = False

        try:
            for file in self.workspace.iter_files(
                payload.path or ".", max_files=self.settings.files_max_search_files
            ):
                if wanted and file.suffix not in wanted:
                    continue
                scanned += 1
                if scanned >= self.settings.files_max_search_files:
                    truncated = True

                name_match = lowered in file.name.lower() or lowered in file.relative_path.lower()
                content_match = False
                snippet = ""

                if file.is_text and file.size <= self.settings.files_max_search_bytes:
                    if payload.include_content or name_match:
                        try:
                            read = read_text_file(
                                self.workspace.resolve(file.relative_path),
                                max_bytes=self.settings.files_max_search_bytes,
                                max_chars=4_000,
                            )
                        except (WorkspaceError, OSError):
                            read = None
                        if read is not None:
                            index = read.text.lower().find(lowered)
                            content_match = index >= 0
                            if content_match:
                                snippet = _around(read.text, index, len(query))
                            elif name_match:
                                snippet = _clean(read.text)[:180]

                if not name_match and not content_match:
                    continue

                match = (
                    "name+content"
                    if name_match and content_match
                    else "name"
                    if name_match
                    else "content"
                )
                items.append(
                    FileSearchItem(
                        path=file.relative_path,
                        name=file.name,
                        size=file.size,
                        modified_at=file.modified_at,
                        match=match,
                        snippet=snippet,
                    )
                )
                if len(items) >= limit:
                    truncated = True
                    break
        except WorkspaceNotFound as error:
            raise ToolExecutionError(ToolErrorCode.FILE_NOT_FOUND, str(error)) from error
        except WorkspaceError as error:
            raise ToolExecutionError(ToolErrorCode.FILE_ACCESS_DENIED, str(error)) from error

        return FileSearchOutput(
            query=query,
            items=items,
            count=len(items),
            scanned=scanned,
            truncated=truncated,
        )


def _extensions(values: list[str] | None) -> frozenset[str]:
    if not values:
        return frozenset()
    normalized = set()
    for value in values:
        suffix = value.strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            suffix = "." + suffix
        normalized.add(suffix)
    return frozenset(normalized)


def _around(text: str, index: int, length: int, radius: int = 90) -> str:
    start = max(0, index - radius)
    end = min(len(text), index + max(length, 1) + radius)
    return _clean(text[start:end])[:220]


def _clean(value: str) -> str:
    return " ".join(value.split())
