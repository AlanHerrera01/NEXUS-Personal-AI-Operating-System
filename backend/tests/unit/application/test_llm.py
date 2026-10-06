import asyncio

import pytest
from fastapi.testclient import TestClient

from app.application.llm.llm_service import LLMService
from app.application.llm.prompt_builder import NEXUS_SYSTEM_PROMPT, PromptBuilder
from app.config.settings import Settings
from app.domain.ports.llm_errors import LLMInvalidRequestError
from app.domain.ports.llm_provider import LLMMessage, LLMMessageRole, LLMRequest, LLMResponse
from app.infrastructure.llm.fake_provider import FakeLLMProvider
from app.infrastructure.llm.nebius.client import NebiusHTTPError
from app.infrastructure.llm.nebius.provider import NebiusLLMProvider
from app.main import app
from app.presentation.dependencies.llm import llm_service_dependency


def test_llm_request_validates_messages_and_parameters() -> None:
    request = LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),), max_tokens=20)

    assert request.messages[0].role is LLMMessageRole.USER
    with pytest.raises(ValueError):
        LLMRequest((), max_tokens=20)
    with pytest.raises(ValueError):
        LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),), temperature=3)


def test_prompt_builder_composes_nexus_system_and_user_messages() -> None:
    messages = PromptBuilder().build("What is NEXUS?")

    assert messages[0].role is LLMMessageRole.SYSTEM
    assert NEXUS_SYSTEM_PROMPT in messages[0].content
    assert messages[1] == LLMMessage(LLMMessageRole.USER, "What is NEXUS?")


def test_fake_provider_is_deterministic_through_llm_service() -> None:
    response = asyncio.run(LLMService(FakeLLMProvider()).generate(LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),))))

    assert isinstance(response, LLMResponse)
    assert response.content == "Fake NEXUS response"


class FakeNebiusClient:
    async def create_chat_completion(self, payload):
        assert payload["model"] == "nvidia/test-nemotron"
        return {
            "model": "nvidia/test-nemotron",
            "choices": [{"message": {"content": "Nemotron response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
        }


class RetryingNebiusClient:
    def __init__(self):
        self.calls = 0

    async def create_chat_completion(self, payload):
        self.calls += 1
        if self.calls == 1:
            raise NebiusHTTPError(503)
        return {"model": payload["model"], "choices": [{"message": {"content": "ok"}}], "usage": {}}


def provider_settings(**overrides):
    values = {"nebius_api_key": "test-key", "nebius_base_url": "unit-test", "nebius_model": "nvidia/test-nemotron"}
    values.update(overrides)
    return Settings(**values)


def test_nebius_provider_maps_response_without_network() -> None:
    provider = NebiusLLMProvider(provider_settings(), client=FakeNebiusClient())

    response = asyncio.run(provider.generate(LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),))))

    assert response.content == "Nemotron response"
    assert response.usage.total_tokens == 7


def test_nebius_provider_retries_transient_errors() -> None:
    client = RetryingNebiusClient()
    provider = NebiusLLMProvider(provider_settings(llm_max_retries=1), client=client)

    response = asyncio.run(provider.generate(LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),))))

    assert response.content == "ok"
    assert client.calls == 2


def test_llm_api_uses_service_dependency_and_returns_dto() -> None:
    app.dependency_overrides[llm_service_dependency] = lambda: LLMService(FakeLLMProvider())
    try:
        response = TestClient(app).post("/api/v1/llm/generate", json={"message": "Explain NEXUS"})
    finally:
        app.dependency_overrides.pop(llm_service_dependency, None)

    assert response.status_code == 200
    assert response.json()["content"] == "Fake NEXUS response"
    assert response.json()["usage"] is None


def test_nebius_invalid_status_is_not_retried_or_exposed() -> None:
    class InvalidClient:
        async def create_chat_completion(self, payload):
            raise NebiusHTTPError(400)

    provider = NebiusLLMProvider(provider_settings(llm_max_retries=2), client=InvalidClient())

    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(provider.generate(LLMRequest((LLMMessage(LLMMessageRole.USER, "Hello"),))))
