from pydantic import BaseModel, Field


class GenerateLLMRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class TokenUsageResponse(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class GenerateLLMResponse(BaseModel):
    content: str
    model: str
    usage: TokenUsageResponse | None = None
    finish_reason: str | None = None
