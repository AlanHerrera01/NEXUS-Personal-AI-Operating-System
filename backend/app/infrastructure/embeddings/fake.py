import hashlib

from app.domain.ports.embedding_provider import EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[index] / 255 for index in range(self.dimensions)]
