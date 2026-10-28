"""``knowledge.search``: retrieve local chunks for the model to cite."""

from __future__ import annotations

from pydantic import Field

from app.application.knowledge.errors import InvalidKnowledgeError
from app.application.knowledge.search_knowledge import (
    MAX_LIMIT,
    SearchKnowledgeUseCase,
)
from app.application.security.injection import fence
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.knowledge.tools.contracts import (
    SKILL_NAME,
    KnowledgeSearchItem,
    KnowledgeSearchOutput,
)

MAX_QUERY_LENGTH = 500

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUERY_LENGTH,
            "description": "Terms to look for in the local knowledge base",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": "Maximum chunks to return",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class KnowledgeSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=5, ge=1, le=MAX_LIMIT)


class KnowledgeSearchTool(UseCaseTool):
    def __init__(self, use_case: SearchKnowledgeUseCase) -> None:
        super().__init__(
            name="knowledge.search",
            description=(
                "Search the local knowledge base and return the most relevant "
                "chunks with their source. Use knowledge.ingest first."
            ),
            skill_name=SKILL_NAME,
            input_model=KnowledgeSearchInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="knowledge",
        )
        self.use_case = use_case

    async def run(
        self, payload: KnowledgeSearchInput, context: ToolContext
    ) -> KnowledgeSearchOutput:
        try:
            matches = self.use_case.execute(
                agent_id=context.agent_id,
                user_id=context.user_id,
                query=payload.query,
                limit=payload.limit,
            )
        except InvalidKnowledgeError as error:
            raise ToolExecutionError(ToolErrorCode.KNOWLEDGE_INVALID, str(error)) from error

        items = [
            KnowledgeSearchItem(
                source=match.chunk.source,
                title=match.chunk.title,
                content=fence(
                    match.chunk.content,
                    source=f"knowledge.search {match.chunk.source}",
                    max_chars=4_000,
                ),
                score=match.score,
                chunk_index=match.chunk.chunk_index,
                created_at=match.chunk.created_at,
            )
            for match in matches
        ]
        return KnowledgeSearchOutput(
            query=payload.query,
            items=items,
            count=len(items),
        )
