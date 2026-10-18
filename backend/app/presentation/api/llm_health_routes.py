from fastapi import APIRouter, Depends

from app.config.settings import Settings
from app.presentation.dependencies.settings import get_effective_settings

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/llm")
def llm_health(settings: Settings = Depends(get_effective_settings)) -> dict[str, object]:
    # Reports the *effective* model, so a runtime override is reflected here and
    # the probe does not disagree with what the next request will actually call.
    return {
        "provider": "nebius",
        "configured": bool(settings.nebius_api_key and settings.nebius_model),
    }
