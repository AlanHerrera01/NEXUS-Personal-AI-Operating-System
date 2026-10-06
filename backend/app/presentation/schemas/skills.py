from pydantic import BaseModel, Field

from app.domain.value_objects.risk_level import RiskLevel


class ToolView(BaseModel):
    """Public tool metadata. Never exposes secrets, credentials or internals."""

    name: str
    skill: str
    description: str
    risk_level: RiskLevel
    read_only: bool
    side_effect: bool
    requires_confirmation: bool
    category: str | None = None
    version: str = "1.0.0"
    input_schema: dict = Field(default_factory=dict)


class SkillView(BaseModel):
    name: str
    description: str
    version: str
    enabled: bool
    category: str | None = None
    keywords: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class SkillsResponse(BaseModel):
    skills: list[SkillView]


class ToolsResponse(BaseModel):
    tools: list[ToolView]
