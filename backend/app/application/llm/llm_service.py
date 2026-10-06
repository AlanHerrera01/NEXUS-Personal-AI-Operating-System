from app.domain.ports.llm_provider import LLMProvider, LLMRequest, LLMResponse


class LLMService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return await self.provider.generate(request)
