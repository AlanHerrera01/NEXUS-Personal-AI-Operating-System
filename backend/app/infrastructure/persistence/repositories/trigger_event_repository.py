"""SQLAlchemy adapter for :class:`TriggerEvent`."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities.trigger_event import TriggerEvent
from app.domain.repositories.trigger_event_repository import TriggerEventRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.datetime_normaliser import ensure_utc
from app.infrastructure.persistence.models import TriggerEventModel


class SqlAlchemyTriggerEventRepository(TriggerEventRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, event: TriggerEvent) -> TriggerEvent:
        model = self.session.get(TriggerEventModel, event.id.value)
        if model is None:
            model = TriggerEventModel(id=event.id.value)
            self.session.add(model)
        self._write(model, event)
        self.session.commit()
        stored = self.session.get(TriggerEventModel, event.id.value)
        return self._to_entity(stored)

    def create_if_absent(self, event: TriggerEvent) -> tuple[TriggerEvent, bool]:
        """Insert unless the idempotency key is taken.

        A webhook provider retrying a delivery lands here and gets the original
        row back, which is what stops a redelivery from dispatching the same job
        a second time.
        """
        existing = self.get_by_idempotency_key(event.idempotency_key)
        if existing is not None:
            return existing, False

        model = TriggerEventModel(id=event.id.value)
        self._write(model, event)
        self.session.add(model)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            winner = self.get_by_idempotency_key(event.idempotency_key)
            if winner is None:
                raise
            return winner, False
        return self._to_entity(self.session.get(TriggerEventModel, event.id.value)), True

    def get_by_id(self, event_id: EntityId) -> TriggerEvent | None:
        model = self.session.get(TriggerEventModel, event_id.value)
        return self._to_entity(model) if model else None

    def get_by_idempotency_key(self, idempotency_key: str) -> TriggerEvent | None:
        model = self.session.scalar(
            select(TriggerEventModel).where(
                TriggerEventModel.idempotency_key == idempotency_key
            )
        )
        return self._to_entity(model) if model else None

    def list_by_user(self, user_id: EntityId, limit: int = 100) -> list[TriggerEvent]:
        models = self.session.scalars(
            select(TriggerEventModel)
            .where(TriggerEventModel.user_id == user_id.value)
            .order_by(TriggerEventModel.received_at.desc())
            .limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def count_by_user_since(self, user_id: EntityId, since: datetime) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(TriggerEventModel)
                .where(
                    TriggerEventModel.user_id == user_id.value,
                    TriggerEventModel.received_at >= ensure_utc(since),
                )
            )
            or 0
        )

    # -- mapping ---------------------------------------------------------

    def _write(self, model: TriggerEventModel, event: TriggerEvent) -> None:
        model.user_id = event.user_id.value
        model.source = event.source
        model.event_type = event.event_type
        model.idempotency_key = event.idempotency_key
        model.payload = dict(event.payload)
        model.received_at = ensure_utc(event.received_at)
        model.processed_at = ensure_utc(event.processed_at)
        model.error_message = event.error_message

    def _to_entity(self, model: TriggerEventModel) -> TriggerEvent:
        return TriggerEvent(
            id=EntityId(model.id),
            user_id=EntityId(model.user_id),
            source=model.source,
            event_type=model.event_type,
            idempotency_key=model.idempotency_key,
            payload=dict(model.payload or {}),
            received_at=ensure_utc(model.received_at),
            processed_at=ensure_utc(model.processed_at),
            error_message=model.error_message,
        )