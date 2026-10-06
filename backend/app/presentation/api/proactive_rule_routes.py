"""HTTP surface for proactive rules.

Deliberately narrow. A rule is a closed condition plus a closed action, both
validated in the domain, so this layer cannot be used to define arbitrary logic
-- the worst a caller can do is pick one of the four condition kinds and one of
the two actions. There is no "expression" or "prompt" field, and adding one would
defeat the point of making triggers deterministic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.application.always_on.errors import AlwaysOnError, ProactiveRuleNotFound
from app.application.always_on.manage_proactive_rule import (
    CreateProactiveRuleUseCase,
    DeleteProactiveRuleUseCase,
    GetProactiveRuleUseCase,
    ListProactiveRulesUseCase,
    SetProactiveRuleEnabledUseCase,
)
from app.config.settings import Settings, get_settings
from app.domain.entities.proactive_rule import ProactiveRule
from app.domain.value_objects.entity_id import EntityId
from app.presentation.dependencies.always_on import (
    get_create_proactive_rule_use_case,
    get_delete_proactive_rule_use_case,
    get_get_proactive_rule_use_case,
    get_list_proactive_rules_use_case,
    get_set_proactive_rule_enabled_use_case,
)
from app.presentation.dependencies.identity import LOCAL_USER_ID

router = APIRouter(prefix="/api/v1/proactive-rules", tags=["always-on"])


class ProactiveRuleResponse(BaseModel):
    id: str
    user_id: str
    agent_id: str
    name: str
    condition: dict
    action: dict
    enabled: bool
    cooldown_seconds: int
    last_triggered_at: str | None
    trigger_count: int
    created_at: str

    @classmethod
    def from_entity(cls, rule: ProactiveRule) -> "ProactiveRuleResponse":
        return cls(
            id=str(rule.id),
            user_id=str(rule.user_id),
            agent_id=str(rule.agent_id),
            name=rule.name,
            condition=rule.condition,
            action=rule.action,
            enabled=rule.enabled,
            cooldown_seconds=rule.cooldown_seconds,
            last_triggered_at=(
                rule.last_triggered_at.isoformat() if rule.last_triggered_at else None
            ),
            trigger_count=rule.trigger_count,
            created_at=rule.created_at.isoformat(),
        )


class CreateProactiveRuleRequest(BaseModel):
    agent_id: str
    name: str = Field(min_length=1, max_length=200)
    condition: dict
    action: dict
    cooldown_seconds: int = Field(default=3_600, ge=60, le=86_400)
    enabled: bool = True


class SetEnabledRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[ProactiveRuleResponse])
async def list_proactive_rules(
    enabled_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    service: ListProactiveRulesUseCase = Depends(get_list_proactive_rules_use_case),
) -> list[ProactiveRuleResponse]:
    rules = service.execute(EntityId(LOCAL_USER_ID), enabled_only, limit)
    return [ProactiveRuleResponse.from_entity(rule) for rule in rules]


@router.post("", response_model=ProactiveRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_proactive_rule(
    body: CreateProactiveRuleRequest,
    service: CreateProactiveRuleUseCase = Depends(get_create_proactive_rule_use_case),
    settings: Settings = Depends(get_settings),
) -> ProactiveRuleResponse:
    if not settings.always_on_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Always-On is disabled in this deployment (always_on_enabled)",
        )

    try:
        rule = service.execute(
            user_id=EntityId(LOCAL_USER_ID),
            agent_id=EntityId.from_string(body.agent_id),
            name=body.name,
            condition=body.condition,
            action=body.action,
            cooldown_seconds=body.cooldown_seconds,
            enabled=body.enabled,
        )
    except AlwaysOnError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ValueError as error:
        # Quota, unknown/inactive agent, or a condition/action the domain
        # refuses. All are the caller's problem, so all are 400.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    return ProactiveRuleResponse.from_entity(rule)


@router.get("/{rule_id}", response_model=ProactiveRuleResponse)
async def get_proactive_rule(
    rule_id: str,
    service: GetProactiveRuleUseCase = Depends(get_get_proactive_rule_use_case),
) -> ProactiveRuleResponse:
    try:
        rule = service.execute(
            EntityId.from_string(rule_id), EntityId(LOCAL_USER_ID)
        )
    except ProactiveRuleNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return ProactiveRuleResponse.from_entity(rule)


@router.post("/{rule_id}/enable", response_model=ProactiveRuleResponse)
async def enable_proactive_rule(
    rule_id: str,
    service: SetProactiveRuleEnabledUseCase = Depends(
        get_set_proactive_rule_enabled_use_case
    ),
) -> ProactiveRuleResponse:
    return _set_enabled(rule_id, True, service)


@router.post("/{rule_id}/disable", response_model=ProactiveRuleResponse)
async def disable_proactive_rule(
    rule_id: str,
    service: SetProactiveRuleEnabledUseCase = Depends(
        get_set_proactive_rule_enabled_use_case
    ),
) -> ProactiveRuleResponse:
    return _set_enabled(rule_id, False, service)


def _set_enabled(
    rule_id: str, enabled: bool, service: SetProactiveRuleEnabledUseCase
) -> ProactiveRuleResponse:
    try:
        rule = service.execute(
            EntityId.from_string(rule_id), EntityId(LOCAL_USER_ID), enabled
        )
    except ProactiveRuleNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return ProactiveRuleResponse.from_entity(rule)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    # Explicit, because FastAPI turns a `-> None` annotation into a truthy
    # `NoneType` response model and then rejects it against a 204.
    response_model=None,
)
async def delete_proactive_rule(
    rule_id: str,
    service: DeleteProactiveRuleUseCase = Depends(get_delete_proactive_rule_use_case),
) -> None:
    try:
        service.execute(EntityId.from_string(rule_id), EntityId(LOCAL_USER_ID))
    except ProactiveRuleNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error