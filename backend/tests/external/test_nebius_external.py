import os

import pytest

from app.config.settings import get_settings
from app.domain.ports.llm_provider import LLMMessage, LLMMessageRole, LLMRequest
from app.infrastructure.llm.nebius.provider import NebiusLLMProvider

pytestmark = pytest.mark.external


@pytest.mark.skipif(
    not all(os.getenv(name) for name in ("NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL")),
    reason="NEBIUS_API_KEY, NEBIUS_BASE_URL and NEBIUS_MODEL are required",
)
def test_nebius_external_generation() -> None:
    import asyncio

    response = asyncio.run(
        NebiusLLMProvider(get_settings()).generate(
            LLMRequest((LLMMessage(LLMMessageRole.USER, "Reply with one short sentence about NEXUS."),))
        )
    )

    assert response.content
    assert response.model
