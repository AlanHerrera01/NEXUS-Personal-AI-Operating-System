from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    title: str


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
