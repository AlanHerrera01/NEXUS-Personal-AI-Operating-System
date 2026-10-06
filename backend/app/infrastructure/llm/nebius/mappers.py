from typing import Any

from app.domain.ports.llm_provider import LLMMessage, LLMRequest, LLMResponse, TokenUsage


def request_to_payload(request: LLMRequest, model: str, temperature: float, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": message.role.value, "content": message.content} for message in request.messages],
        "temperature": request.temperature if request.temperature is not None else temperature,
        "max_tokens": request.max_tokens if request.max_tokens is not None else max_tokens,
    }


def response_from_payload(payload: dict[str, Any], requested_model: str) -> LLMResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Nebius response did not contain choices")
    choice = choices[0]
    message = choice.get("message") or {}
    usage = payload.get("usage")
    return LLMResponse(
        content=str(message.get("content") or ""),
        model=str(payload.get("model") or requested_model),
        usage=(
            TokenUsage(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            if usage is not None
            else None
        ),
        finish_reason=choice.get("finish_reason"),
    )
