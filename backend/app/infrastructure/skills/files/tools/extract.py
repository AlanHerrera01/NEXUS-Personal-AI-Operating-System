"""``docs.extract``: turn PDF, DOCX or XLSX into text the model can read."""

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
    extract_document,
)
from app.infrastructure.skills.files.tools.contracts import (
    SKILL_NAME,
    DocumentExtractOutput,
)

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
            "description": "Document path relative to the workspace root",
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


class DocumentExtractInput(ToolInput):
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    max_chars: int | None = Field(default=None, ge=MIN_CHARS, le=MAX_CHARS)


class DocumentExtractTool(UseCaseTool[DocumentExtractInput, DocumentExtractOutput]):
    def __init__(self, workspace: Workspace, settings: Settings) -> None:
        super().__init__(
            name="docs.extract",
            description=(
                "Extract readable text from a PDF, DOCX, XLSX or text document "
                "inside the workspace. Returns metadata and a bounded excerpt."
            ),
            skill_name=SKILL_NAME,
            input_model=DocumentExtractInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="documents",
        )
        self.workspace = workspace
        self.settings = settings

    async def run(
        self, payload: DocumentExtractInput, context: ToolContext
    ) -> DocumentExtractOutput:
        limit = payload.max_chars or 20_000
        try:
            file = self.workspace.file(payload.path)
            extracted = extract_document(
                self.workspace.resolve(file.relative_path),
                max_bytes=self.settings.files_max_extract_bytes,
                max_chars=limit,
            )
        except WorkspaceNotFound as error:
            raise ToolExecutionError(ToolErrorCode.FILE_NOT_FOUND, str(error)) from error
        except WorkspaceAccessDenied as error:
            raise ToolExecutionError(ToolErrorCode.FILE_ACCESS_DENIED, str(error)) from error
        except WorkspaceFileTooLarge as error:
            raise ToolExecutionError(ToolErrorCode.FILE_TOO_LARGE, str(error)) from error
        except WorkspaceUnsupported as error:
            raise ToolExecutionError(
                ToolErrorCode.DOCUMENT_EXTRACTION_FAILED, str(error)
            ) from error

        if not extracted.text.strip():
            raise ToolExecutionError(
                ToolErrorCode.DOCUMENT_EXTRACTION_FAILED,
                "the document contains no extractable text",
            )

        return DocumentExtractOutput(
            path=file.relative_path,
            format=extracted.format,
            content=fence(
                extracted.text,
                source=f"docs.extract {file.relative_path}",
                max_chars=limit,
            ),
            size=extracted.size,
            modified_at=extracted.modified_at,
            truncated=extracted.truncated,
            metadata=extracted.metadata,
        )
