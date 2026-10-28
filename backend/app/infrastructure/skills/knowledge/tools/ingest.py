"""``knowledge.ingest``: add a workspace document or raw note to local RAG."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.application.knowledge.errors import InvalidKnowledgeError
from app.application.knowledge.ingest_knowledge import IngestKnowledgeUseCase
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.documents import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceFileTooLarge,
    WorkspaceNotFound,
    WorkspaceUnsupported,
    extract_document,
)
from app.infrastructure.skills.knowledge.tools.contracts import (
    SKILL_NAME,
    KnowledgeIngestOutput,
)

MAX_TEXT_LENGTH = 200_000
MAX_PATH_LENGTH = 1_000
MAX_TITLE_LENGTH = 300
MAX_SOURCE_LENGTH = 1_000

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": ["string", "null"],
            "maxLength": MAX_PATH_LENGTH,
            "description": "Workspace document to ingest; mutually exclusive with text",
        },
        "text": {
            "type": ["string", "null"],
            "maxLength": MAX_TEXT_LENGTH,
            "description": "Raw text to ingest; mutually exclusive with path",
        },
        "title": {
            "type": ["string", "null"],
            "maxLength": MAX_TITLE_LENGTH,
            "description": "Human-readable document title",
        },
        "source": {
            "type": ["string", "null"],
            "maxLength": MAX_SOURCE_LENGTH,
            "description": "Source label; defaults to the path or 'manual'",
        },
    },
    "required": [],
    "additionalProperties": False,
}


class KnowledgeIngestInput(ToolInput):
    path: str | None = Field(default=None, max_length=MAX_PATH_LENGTH)
    text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LENGTH)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "KnowledgeIngestInput":
        if bool(self.path) == bool(self.text):
            raise ValueError("provide exactly one of path or text")
        return self


class KnowledgeIngestTool(UseCaseTool):
    def __init__(self, use_case: IngestKnowledgeUseCase, workspace: Workspace, settings: Settings) -> None:
        super().__init__(
            name="knowledge.ingest",
            description=(
                "Add a workspace document or a raw note to the local knowledge "
                "base. Text is split into chunks and searched locally."
            ),
            skill_name=SKILL_NAME,
            input_model=KnowledgeIngestInput,
            input_schema=INPUT_SCHEMA,
            risk_level=RiskLevel.MEDIUM,
            side_effect=True,
            category="knowledge",
        )
        self.use_case = use_case
        self.workspace = workspace
        self.settings = settings

    async def run(
        self, payload: KnowledgeIngestInput, context: ToolContext
    ) -> KnowledgeIngestOutput:
        source = (payload.source or "").strip()
        title = (payload.title or "").strip()

        if payload.path:
            try:
                file = self.workspace.file(payload.path)
                extracted = extract_document(
                    self.workspace.resolve(file.relative_path),
                    max_bytes=self.settings.files_max_extract_bytes,
                    max_chars=self.settings.knowledge_max_document_chars,
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
            text = extracted.text
            source = source or file.relative_path
            title = title or file.name
        else:
            text = payload.text or ""
            source = source or "manual"
            title = title or "Nota de conocimiento"

        try:
            result = self.use_case.execute(
                agent_id=context.agent_id,
                user_id=context.user_id,
                source=source,
                title=title,
                text=text,
                max_document_chars=self.settings.knowledge_max_document_chars,
                chunk_chars=self.settings.knowledge_chunk_chars,
                chunk_overlap=self.settings.knowledge_chunk_overlap,
            )
        except InvalidKnowledgeError as error:
            raise ToolExecutionError(ToolErrorCode.KNOWLEDGE_INVALID, str(error)) from error

        return KnowledgeIngestOutput(
            source=result.source,
            title=result.title,
            chunks=result.chunks,
            characters=result.characters,
            created=result.created,
            document_hash=result.document_hash,
        )
