from fastapi import APIRouter, Depends, HTTPException, status

from app.application.llm.llm_service import LLMService
from app.application.llm.prompt_builder import PromptBuilder
from app.domain.ports.llm_errors import LLMProviderError
from app.domain.ports.llm_provider import LLMRequest
from app.presentation.dependencies.llm import llm_service_dependency
from app.presentation.schemas.llm import GenerateLLMRequest, GenerateLLMResponse, TokenUsageResponse

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


@router.post("/generate", response_model=GenerateLLMResponse)
async def generate(
    payload: GenerateLLMRequest,
    service: LLMService = Depends(llm_service_dependency),
) -> GenerateLLMResponse:
    request = LLMRequest(messages=PromptBuilder().build(payload.message))
    try:
        response = await service.generate(request)
    except LLMProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM provider unavailable") from error
    return GenerateLLMResponse(
        content=response.content,
        model=response.model,
        finish_reason=response.finish_reason,
        usage=(
            TokenUsageResponse(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
            if response.usage
            else None
        ),
    )
