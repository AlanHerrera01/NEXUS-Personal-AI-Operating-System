from fastapi import APIRouter

from app.config.settings import get_settings

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/llm")
def llm_health() -> dict[str, object]:
    settings = get_settings()
    return {
        "provider": "nebius",
        "configured": bool(settings.nebius_api_key and settings.nebius_model),
    }
