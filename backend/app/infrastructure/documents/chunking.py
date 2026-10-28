"""Paragraph-aware chunking for the local knowledge base.

The goal is not perfect retrieval theory; it is chunks that a model can cite
without cutting a sentence in half. Overlap is small and bounded so a document
does not turn into a quadratic amount of stored text.
"""

from __future__ import annotations


def chunk_text(text: str, *, max_chars: int = 1_200, overlap: int = 150) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    max_chars = max(200, max_chars)
    overlap = max(0, min(overlap, max_chars // 2))
    chunks: list[str] = []
    start = 0

    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            window_start = start + max_chars // 2
            candidates = [
                normalized.rfind("\n\n", window_start, end),
                normalized.rfind("\n", window_start, end),
                normalized.rfind(". ", window_start, end),
            ]
            boundary = max(candidates)
            if boundary >= window_start:
                if normalized.startswith(". ", boundary):
                    end = boundary + 2
                else:
                    end = boundary + 1

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)

    return chunks
