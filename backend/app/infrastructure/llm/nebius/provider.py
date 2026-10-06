import asyncio
import logging
import time

from app.config.settings import Settings
from app.domain.ports.llm_errors import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports.llm_provider import LLMProvider, LLMRequest, LLMResponse
from app.infrastructure.llm.nebius.client import NebiusClient, NebiusHTTPError, NebiusTransportError
from app.infrastructure.llm.nebius.mappers import request_to_payload, response_from_payload

logger = logging.getLogger(__name__)


class NebiusLLMProvider(LLMProvider):
    def __init__(self, settings: Settings, client: NebiusClient | None = None) -> None:
        self.settings = settings
        self.client = client or self._build_client()

    @property
    def configured(self) -> bool:
        return bool(self.settings.nebius_api_key and self.settings.nebius_base_url and self.settings.nebius_model)

    def _build_client(self) -> NebiusClient | None:
        if not self.settings.nebius_api_key or not self.settings.nebius_base_url:
            return None
        return NebiusClient(self.settings.nebius_base_url, self.settings.nebius_api_key, self.settings.llm_timeout)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.settings.nebius_model
        if not self.settings.nebius_api_key:
            raise LLMAuthenticationError("NEBIUS_API_KEY is not configured")
        if not model:
            raise LLMInvalidRequestError("NEBIUS_MODEL is not configured")
        if not self.settings.nebius_base_url:
            raise LLMInvalidRequestError("NEBIUS_BASE_URL is not configured")
        if self.client is None:
            raise LLMAuthenticationError("NEBIUS_API_KEY is not configured")

        payload = request_to_payload(request, model, self.settings.llm_temperature, self.settings.llm_max_tokens)
        started = time.perf_counter()
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                response_payload = await self.client.create_chat_completion(payload)
                response = response_from_payload(response_payload, model)
                logger.info(
                    "LLM request completed model=%s duration_ms=%d total_tokens=%s",
                    response.model,
                    int((time.perf_counter() - started) * 1000),
                    response.usage.total_tokens if response.usage else None,
                )
                return response
            except NebiusTransportError as error:
                if attempt >= self.settings.llm_max_retries:
                    raise LLMTimeoutError("Nebius request failed after retries") from error
            except NebiusHTTPError as error:
                if error.status_code in {401, 403}:
                    raise LLMAuthenticationError("Nebius authentication failed") from error
                if error.status_code == 429:
                    if attempt >= self.settings.llm_max_retries:
                        raise LLMRateLimitError("Nebius rate limit exceeded") from error
                elif error.status_code == 408 or error.status_code >= 500:
                    if attempt >= self.settings.llm_max_retries:
                        raise LLMUnavailableError("Nebius service unavailable") from error
                else:
                    raise LLMInvalidRequestError("Nebius rejected the request") from error
            await asyncio.sleep(0.2 * (attempt + 1))

        raise LLMUnavailableError("Nebius request did not complete")
