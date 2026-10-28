"""OpenAI-compatible embedding transport, independent of the chat model."""
from __future__ import annotations

import hashlib
import math

import httpx

from app.config.settings import Settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    @property
    def fingerprint(self) -> str:
        identity = f"{self.settings.embedding_base_url.rstrip('/')}|{self.settings.embedding_model}|{self.settings.embedding_dimensions}"
        return hashlib.sha256(identity.encode()).hexdigest()

    def embed(self, content: str) -> list[float]:
        try:
            with httpx.Client(timeout=self.settings.embedding_timeout_seconds, follow_redirects=False, transport=self.transport) as client:
                with client.stream(
                    "POST", self.settings.embedding_base_url.rstrip("/") + "/embeddings",
                    headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"},
                    json={"model": self.settings.embedding_model, "input": content, "encoding_format": "float"},
                ) as response:
                    if response.status_code != 200:
                        raise EmbeddingError(f"Embedding provider returned HTTP {response.status_code}.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_048_576:
                            raise EmbeddingError("Embedding response exceeded the size limit.")
            import json
            vector = json.loads(body)["data"][0]["embedding"]
            if not isinstance(vector, list) or len(vector) != self.settings.embedding_dimensions:
                raise EmbeddingError("Embedding dimensions do not match EMBEDDING_DIMENSIONS.")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
                raise EmbeddingError("Embedding provider returned invalid vector values.")
            norm = math.sqrt(sum(float(value) ** 2 for value in vector))
            if not math.isfinite(norm) or norm == 0:
                raise EmbeddingError("Embedding provider returned a zero or invalid vector.")
            return [float(value) / norm for value in vector]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OverflowError) as error:
            # Never include response bodies, input memory or credentials in an error.
            raise EmbeddingError("Embedding provider failed or returned an invalid response.") from error
