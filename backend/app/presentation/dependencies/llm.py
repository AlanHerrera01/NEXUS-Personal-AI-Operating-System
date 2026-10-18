from fastapi import Depends

from app.application.llm.llm_service import LLMService
from app.config.settings import Settings
from app.infrastructure.llm.nebius.provider import NebiusLLMProvider
from app.presentation.dependencies.settings import get_effective_settings


def llm_service_dependency(
    settings: Settings = Depends(get_effective_settings),
) -> LLMService:
    """The LLM service built from the *effective* settings.

    This is the point where a saved override becomes live: the provider reads its
    model, temperature, max-tokens and timeout off the ``Settings`` it is handed,
    and it is handed the merged configuration rather than the boot one. Nothing
    inside the provider needs to know overrides exist.
    """
    return LLMService(NebiusLLMProvider(settings))
