"""``files.read``: read one text file from the workspace."""

from __future__ import annotations

from pydantic import Field

from app.application.security.injection import fence
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.documents import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceFileTooLarge,
    WorkspaceNotFound,
    WorkspaceUnsupported,
    read_text_file,
)
from app.infrastructure.skills.files.tools.contracts import SKILL_NAME, FileReadOutput

MAX_PATH_LENGTH = 1_000
MIN_CHARS = 200
MAX_CHARS = 50_000

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PATH_LENGTH,
            "description": "Path relative to the workspace root",
        },
        "max_chars": {
            "type": ["integer", "null"],
            "minimum": MIN_CHARS,
            "maximum": MAX_CHARS,
            "description": "Maximum characters to return",
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}


class FileReadInput(ToolInput):
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    max_chars: int | None = Field(default=None, ge=MIN_CHARS, le=MAX_CHARS)


class FileReadTool(UseCaseTool[FileReadInput, FileReadOutput]):
    def __init__(self, workspace: Workspace, settings: Settings) -> None:
        super().__init__(
            name="files.read",
            description=(
                "Read a text, markdown, code, JSON or CSV file inside the "
                "workspace. Use docs.extract for PDF, DOCX or XLSX."
            ),
            skill_name=SKILL_NAME,
            input_model=FileReadInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="files",
        )
        self.workspace = workspace
        self.settings = settings

    async def run(self, payload: FileReadInput, context: ToolContext) -> FileReadOutput:
        try:
            file = self.workspace.file(payload.path)
            if file.is_document:
                raise ToolExecutionError(
                    ToolErrorCode.FILE_UNSUPPORTED,
                    f"{file.relative_path} is a {file.suffix} document; use docs.extract.",
                )
            if not file.is_text and file.suffix:
                raise ToolExecutionError(
                    ToolErrorCode.FILE_UNSUPPORTED,
                    f"unsupported text type: {file.suffix}",
                )
            read = read_text_file(
                self.workspace.resolve(file.relative_path),
                max_bytes=self.settings.files_max_read_bytes,
                max_chars=payload.max_chars or 20_000,
            )
        except ToolExecutionError:
            raise
        except WorkspaceNotFound as error:
            raise ToolExecutionError(ToolErrorCode.FILE_NOT_FOUND, str(error)) from error
        except WorkspaceAccessDenied as error:
            raise ToolExecutionError(ToolErrorCode.FILE_ACCESS_DENIED, str(error)) from error
        except WorkspaceFileTooLarge as error:
            raise ToolExecutionError(ToolErrorCode.FILE_TOO_LARGE, str(error)) from error
        except WorkspaceUnsupported as error:
            raise ToolExecutionError(ToolErrorCode.FILE_UNSUPPORTED, str(error)) from error

        return FileReadOutput(
            path=file.relative_path,
            content=fence(
                read.text,
                source=f"files.read {file.relative_path}",
                max_chars=payload.max_chars or 20_000,
            ),
            size=read.size,
            modified_at=read.modified_at,
            truncated=read.truncated,
        )
