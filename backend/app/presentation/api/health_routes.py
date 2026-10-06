from fastapi import APIRouter

from app.infrastructure.persistence.database import is_database_available
from app.presentation.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
@router.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="nexus-backend",
        phase="4",
        database="up" if is_database_available() else "down",
    )
