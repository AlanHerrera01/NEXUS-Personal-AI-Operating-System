from pydantic import BaseModel, Field

from app.domain.value_objects.permission_decision import PermissionDecision


class CreateAgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class ResumeAgentRunRequest(BaseModel):
    permission: PermissionDecision


class AnswerAgentRunRequest(BaseModel):
    #: The detail the agent asked for. Bounded like the original request so a
    #: clarification cannot become a way to push unlimited text into the prompt.
    answer: str = Field(min_length=1, max_length=4000)


class AgentActionResponse(BaseModel):
    tool_name: str
    status: str
    arguments: dict


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    #: The request the run was created for. Carried on the read so a run reopened
    #: from a list -- a recent run in the sidebar -- can render its own thread
    #: without a second lookup against the overview.
    user_request: str | None = None
    response: str | None = None
    question: str | None = None
    conversation_id: str | None = None
    #: When the run started. Carried so a reopened conversation can show each
    #: exchange at the time it happened rather than at the time it was read.
    created_at: str | None = None
    actions: list[AgentActionResponse] = []
