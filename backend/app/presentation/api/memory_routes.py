from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.memory.clear_memories import ClearMemoriesUseCase
from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.list_memories import ListMemoriesUseCase
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.memory.service import MemoryService
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.value_objects.entity_id import EntityId
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.memory import memory_service_dependency
from app.presentation.schemas.memory import (
    CreateMemoryRequest,
    MemoryDecisionResponse,
    MemoryListResponse,
    MemoryResponse,
    SearchMemoryRequest,
)

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


def to_response(memory) -> MemoryResponse:
    return MemoryResponse(
        id=str(memory.id),
        agent_id=str(memory.agent_id),
        content=memory.content,
        memory_type=memory.memory_type.value,
        source=memory.source.value,
        importance=memory.importance.value,
        persistence_decision=memory.persistence_decision.value,
    )


@router.post("", response_model=MemoryDecisionResponse)
def save_memory(
    payload: CreateMemoryRequest,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> MemoryDecisionResponse:
    candidate = MemoryCandidate(
        agent_id=EntityId(payload.agent_id),
        content=payload.content,
        memory_type=payload.memory_type,
        source=payload.source,
        importance=payload.importance,
        requested_persistence=payload.requested_persistence,
        user_instruction=payload.user_instruction,
        # The owner comes from the resolved identity, never from the request body.
        # A body-supplied user_id would let the caller write into someone else's
        # memory space, and would also let them read it back later.
        user_id=user_id,
    )
    result = SaveMemoryUseCase(service).execute(candidate)
    return MemoryDecisionResponse(
        saved=result.memory is not None,
        decision=result.decision.persistence.value,
        reason=result.decision.reason,
        memory=to_response(result.memory) if result.memory else None,
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(
    memory_id: UUID,
    agent_id: UUID,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> MemoryResponse:
    memory = GetMemoryUseCase(service).execute(
        EntityId(memory_id), EntityId(agent_id), user_id
    )
    if memory is None:
        # 404 rather than 403: a caller who is not the owner should not be able
        # to distinguish "this exists but is not yours" from "this does not exist",
        # because that difference is itself an enumeration oracle.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return to_response(memory)


@router.get("", response_model=MemoryListResponse)
def list_memories(
    agent_id: UUID,
    limit: int = 100,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> MemoryListResponse:
    return MemoryListResponse(
        items=[
            to_response(item)
            for item in ListMemoriesUseCase(service).execute(
                EntityId(agent_id), user_id, limit
            )
        ]
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: UUID,
    agent_id: UUID,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> None:
    if not DeleteMemoryUseCase(service).execute(
        EntityId(memory_id), EntityId(agent_id), user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")


@router.delete("", response_model=dict[str, int])
def clear_memories(
    agent_id: UUID,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> dict[str, int]:
    return {"deleted": ClearMemoriesUseCase(service).execute(EntityId(agent_id), user_id)}


@router.post("/search", response_model=MemoryListResponse)
def search_memories(
    payload: SearchMemoryRequest,
    service: MemoryService = Depends(memory_service_dependency),
    user_id=Depends(current_user_id),
) -> MemoryListResponse:
    memories = SearchMemoriesUseCase(service).execute(
        EntityId(payload.agent_id), user_id, payload.query, payload.limit
    )
    return MemoryListResponse(items=[to_response(item) for item in memories])
