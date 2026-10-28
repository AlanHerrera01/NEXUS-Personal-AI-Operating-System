import httpx
import pytest

from app.config.settings import Settings
from app.infrastructure.llm.embeddings import EmbeddingError, EmbeddingProvider


def settings(**overrides):
    values = dict(_env_file=None, memory_search_mode="semantic", embedding_base_url="https://embed.example/v1", embedding_api_key="private-key", embedding_model="test-model", embedding_dimensions=2)
    values.update(overrides)
    return Settings(**values)


def test_real_embedding_request_and_normalization():
    def handler(request):
        import json
        assert str(request.url) == "https://embed.example/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert json.loads(request.content)["input"] == "memory text"
        return httpx.Response(200, json={"data": [{"embedding": [3, 4]}]})
    provider = EmbeddingProvider(settings(), transport=httpx.MockTransport(handler))
    assert provider.embed("memory text") == [0.6, 0.8]
    assert provider.fingerprint != EmbeddingProvider(settings(embedding_model="other-model")).fingerprint


@pytest.mark.parametrize("vector", [[0, 0], [1], [True, 1], ["1", "2"], [float("inf"), 1]])
def test_invalid_embeddings_are_refused(vector):
    def handler(_request):
        import json
        return httpx.Response(200, content=json.dumps({"data": [{"embedding": vector}]}))
    with pytest.raises(EmbeddingError):
        EmbeddingProvider(settings(), transport=httpx.MockTransport(handler)).embed("private memory")


def test_provider_failure_is_not_a_keyword_fallback_or_secret_leak():
    provider = EmbeddingProvider(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(401, text="private-key private memory")))
    with pytest.raises(EmbeddingError) as error:
        provider.embed("private memory")
    assert "private-key" not in str(error.value)
    assert "private memory" not in str(error.value)


def test_semantic_mode_requires_explicit_configuration():
    with pytest.raises(ValueError):
        Settings(_env_file=None, memory_search_mode="semantic")
