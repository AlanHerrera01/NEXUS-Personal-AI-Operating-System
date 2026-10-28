from datetime import datetime

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "knowledge"


class KnowledgeIngestOutput(ToolOutput):
    source: str
    title: str
    chunks: int
    characters: int
    created: bool
    document_hash: str


class KnowledgeSearchItem(ToolOutput):
    source: str
    title: str
    content: str
    score: float
    chunk_index: int
    created_at: datetime


class KnowledgeSearchOutput(ToolOutput):
    query: str
    items: list[KnowledgeSearchItem]
    count: int
