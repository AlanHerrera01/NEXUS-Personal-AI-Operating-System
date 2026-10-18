"""Request/response models for the agent registry.

An agent is what a run belongs to: ``POST /api/v1/agents/{id}/runs`` needs one,
and the dashboard treats the caller's active agent as the one the objective bar
runs against. These models exist because there was no way to create that agent
over HTTP, which left those screens with nothing to talk to.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: The two states the entity knows, as wire values. Spelled here rather than
#: imported from the domain enum so the schema does not depend on the value
#: object's repr.
AgentStatusValue = Literal["ACTIVE", "INACTIVE"]


class AgentView(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str


class AgentsResponse(BaseModel):
    items: list[AgentView]
    #: The agent the dashboard would use for a quick action -- the oldest ACTIVE
    #: one -- or None when the caller has none active. Selected the same way
    #: ``GET /api/v1/overview`` selects it, so the two cannot name different
    #: agents.
    active_id: str | None = None


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class UpdateAgentRequest(BaseModel):
    """A partial update: omit a field to leave it alone."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    status: AgentStatusValue | None = None
