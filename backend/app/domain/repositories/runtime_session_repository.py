from abc import ABC, abstractmethod

from app.domain.entities.runtime_session import RuntimeSession
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_state import RuntimeState


class RuntimeSessionRepository(ABC):
    @abstractmethod
    def save(self, session: RuntimeSession) -> RuntimeSession:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, session_id: EntityId) -> RuntimeSession | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_run_id(self, agent_run_id: EntityId) -> list[RuntimeSession]:
        raise NotImplementedError

    @abstractmethod
    def list_by_state(self, state: RuntimeState) -> list[RuntimeSession]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, session_id: EntityId) -> None:
        raise NotImplementedError
