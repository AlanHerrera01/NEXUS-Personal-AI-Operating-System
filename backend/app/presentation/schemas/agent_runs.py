from pydantic import BaseModel, Field

from app.domain.value_objects.permission_decision import PermissionDecision


class CreateAgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)


class ResumeAgentRunRequest(BaseModel):
    permission: PermissionDecision


class AgentActionResponse(BaseModel):
    tool_name: str
    status: str
    arguments: dict


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    response: str | None = None
    question: str | None = None
    actions: list[AgentActionResponse] = []
