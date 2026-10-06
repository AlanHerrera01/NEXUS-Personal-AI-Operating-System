from app.domain.ports.llm_provider import LLMProvider, LLMRequest, LLMResponse, TokenUsage


class FakeLLMProvider(LLMProvider):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content="Fake NEXUS response",
            model=request.model or "fake-model",
            usage=None,
            finish_reason="stop",
        )
