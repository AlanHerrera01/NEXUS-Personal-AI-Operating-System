"""SQLAlchemy adapter for :class:`ProactiveRule`."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities.proactive_rule import ProactiveRule
from app.domain.repositories.proactive_rule_repository import ProactiveRuleRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.datetime_normaliser import ensure_utc
from app.infrastructure.persistence.models import ProactiveRuleModel


class SqlAlchemyProactiveRuleRepository(ProactiveRuleRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, rule: ProactiveRule) -> ProactiveRule:
        model = self.session.get(ProactiveRuleModel, rule.id.value)
        if model is None:
            model = ProactiveRuleModel(id=rule.id.value)
            self.session.add(model)
        self._write(model, rule)
        self.session.commit()
        stored = self.session.get(ProactiveRuleModel, rule.id.value)
        return self._to_entity(stored)

    def get_by_id(self, rule_id: EntityId) -> ProactiveRule | None:
        model = self.session.get(ProactiveRuleModel, rule_id.value)
        return self._to_entity(model) if model else None

    def list_by_user(
        self, user_id: EntityId, enabled_only: bool = False, limit: int = 100
    ) -> list[ProactiveRule]:
        statement = select(ProactiveRuleModel).where(
            ProactiveRuleModel.user_id == user_id.value
        )
        if enabled_only:
            statement = statement.where(ProactiveRuleModel.enabled.is_(True))
        models = self.session.scalars(
            statement.order_by(ProactiveRuleModel.created_at.desc()).limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def count_by_user(self, user_id: EntityId) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(ProactiveRuleModel)
                .where(ProactiveRuleModel.user_id == user_id.value)
            )
            or 0
        )

    def delete(self, rule_id: EntityId) -> None:
        model = self.session.get(ProactiveRuleModel, rule_id.value)
        if model is not None:
            self.session.delete(model)
            self.session.commit()

    # -- mapping ---------------------------------------------------------

    def _write(self, model: ProactiveRuleModel, rule: ProactiveRule) -> None:
        model.user_id = rule.user_id.value
        model.agent_id = rule.agent_id.value
        model.name = rule.name
        model.condition = dict(rule.condition)
        model.action = dict(rule.action)
        model.enabled = rule.enabled
        model.cooldown_seconds = rule.cooldown_seconds
        model.last_triggered_at = ensure_utc(rule.last_triggered_at)
        model.trigger_count = rule.trigger_count
        model.created_at = ensure_utc(rule.created_at)
        model.updated_at = ensure_utc(rule.updated_at)

    def _to_entity(self, model: ProactiveRuleModel) -> ProactiveRule:
        return ProactiveRule(
            id=EntityId(model.id),
            user_id=EntityId(model.user_id),
            agent_id=EntityId(model.agent_id),
            name=model.name,
            condition=dict(model.condition or {}),
            action=dict(model.action or {}),
            enabled=model.enabled,
            cooldown_seconds=model.cooldown_seconds,
            last_triggered_at=ensure_utc(model.last_triggered_at),
            trigger_count=model.trigger_count,
            created_at=ensure_utc(model.created_at),
            updated_at=ensure_utc(model.updated_at),
        )