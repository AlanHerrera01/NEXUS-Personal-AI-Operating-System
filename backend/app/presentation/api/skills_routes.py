from fastapi import APIRouter, Depends

from app.presentation.dependencies.agent import SkillSystem, skill_system_dependency
from app.presentation.schemas.skills import SkillView, SkillsResponse, ToolsResponse, ToolView

router = APIRouter(prefix="/api/v1", tags=["skills"])


@router.get("/skills", response_model=SkillsResponse)
def list_skills(system: SkillSystem = Depends(skill_system_dependency)) -> SkillsResponse:
    return SkillsResponse(
        skills=[
            SkillView(
                name=definition.name,
                description=definition.description,
                version=definition.version,
                enabled=definition.enabled,
                category=definition.category,
                keywords=list(definition.keywords),
                tools=[tool.definition().name for tool in system.skills.tools_for(definition.name)],
            )
            for definition in system.skills.definitions()
        ]
    )


@router.get("/tools", response_model=ToolsResponse)
def list_tools(system: SkillSystem = Depends(skill_system_dependency)) -> ToolsResponse:
    return ToolsResponse(
        tools=[
            ToolView(
                name=definition.name,
                skill=definition.skill_name,
                description=definition.description,
                risk_level=definition.risk_level,
                read_only=definition.read_only,
                side_effect=definition.side_effect,
                requires_confirmation=definition.requires_confirmation,
                category=definition.category,
                version=definition.version,
                input_schema=definition.input_schema,
            )
            for definition in system.tools.definitions()
        ]
    )
