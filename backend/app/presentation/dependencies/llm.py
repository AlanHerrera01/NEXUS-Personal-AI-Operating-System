from app.application.llm.llm_service import LLMService
from app.config.settings import get_settings
from app.infrastructure.llm.nebius.provider import NebiusLLMProvider


def llm_service_dependency() -> LLMService:
    return LLMService(NebiusLLMProvider(get_settings()))
