"""Workspace-safe file access and document text extraction.

The skills that touch files (``files`` and ``knowledge``) share this package so
the jail, the size ceilings and the "no secrets" rule are implemented once. A
second implementation would be a second place to get path traversal wrong.
"""

from app.infrastructure.documents.chunking import chunk_text
from app.infrastructure.documents.extractors import (
    ExtractionResult,
    TextReadResult,
    extract_document,
    read_text_file,
)
from app.infrastructure.documents.workspace import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceError,
    WorkspaceFileTooLarge,
    WorkspaceNotFound,
    WorkspaceUnsupported,
)

__all__ = (
    "ExtractionResult",
    "TextReadResult",
    "Workspace",
    "WorkspaceAccessDenied",
    "WorkspaceError",
    "WorkspaceFileTooLarge",
    "WorkspaceNotFound",
    "WorkspaceUnsupported",
    "chunk_text",
    "extract_document",
    "read_text_file",
)
