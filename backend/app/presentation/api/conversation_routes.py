from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.repositories.agent_action_repository import SqlAlchemyAgentActionRepository
from app.infrastructure.persistence.repositories.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.repositories.conversation_repository import SqlAlchemyConversationRepository
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.persistence import session_dependency
from app.presentation.schemas.agent_runs import AgentActionResponse, AgentRunResponse
from app.presentation.schemas.conversations import ConversationResponse, CreateConversationRequest

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: CreateConversationRequest,
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> ConversationResponse:
    """Create a new conversation."""
    conversation = Conversation(
        title=payload.title,
        user_id=user_id,
    )
    repo = SqlAlchemyConversationRepository(session)
    saved = await repo.save(conversation)
    return ConversationResponse(
        id=str(saved.id),
        title=saved.title,
        created_at=saved.created_at.isoformat(),
        updated_at=saved.updated_at.isoformat(),
    )


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> list[ConversationResponse]:
    """List all conversations for the current user."""
    repo = SqlAlchemyConversationRepository(session)
    conversations = await repo.list_by_user(user_id)
    return [
        ConversationResponse(
            id=str(conv.id),
            title=conv.title,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
        )
        for conv in conversations
    ]


@router.get("/{conversation_id}/runs", response_model=list[AgentRunResponse])
def list_conversation_runs(
    conversation_id: UUID,
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> list[AgentRunResponse]:
    """The runs of one conversation, oldest first, so the chat can replay it.

    Owner-scoped: the conversation id is a URL parameter, so the user filter is
    what stops a caller from reading back somebody else's thread. Each run
    carries its request, its answer and its actions, which is everything the
    conversation view needs to rebuild the exchanges in order.
    """
    run_repo = SqlAlchemyAgentRunRepository(session)
    action_repo = SqlAlchemyAgentActionRepository(session)
    runs = run_repo.list_by_conversation(EntityId(conversation_id), user_id)
    return [
        AgentRunResponse(
            run_id=str(run.id),
            status=run.status.value,
            user_request=run.user_request,
            response=run.response,
            question=run.question,
            created_at=run.created_at.isoformat(),
            actions=[
                AgentActionResponse(
                    tool_name=action.action_name,
                    status=action.status.value,
                    arguments=action.arguments,
                )
                for action in action_repo.list_by_run(run.id)
            ],
        )
        for run in runs
    ]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> ConversationResponse:
    """Get a specific conversation by ID."""
    repo = SqlAlchemyConversationRepository(session)
    conversation = await repo.get_by_id(EntityId(conversation_id))
    # Owner-scoped: the id comes from the URL, so a read that ignored the owner
    # would hand back another user's conversation.
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(
        id=str(conversation.id),
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> Response:
    """Delete a conversation and the runs that belong to it.

    Owner-scoped, like the reads. The runs are removed first, through the run
    repository, so their permission requests go too; the foreign key would only
    detach them, leaving orphaned history behind.
    """
    repo = SqlAlchemyConversationRepository(session)
    conversation = await repo.get_by_id(EntityId(conversation_id))
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    run_repo = SqlAlchemyAgentRunRepository(session)
    for run in run_repo.list_by_conversation(EntityId(conversation_id), user_id):
        run_repo.delete(run.id, user_id)
    await repo.delete(EntityId(conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
