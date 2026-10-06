from abc import ABC, abstractmethod

from app.domain.entities.permission_request import PermissionRequest
from app.domain.value_objects.entity_id import EntityId


class PermissionRequestRepository(ABC):
    @abstractmethod
    def save(self, request: PermissionRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, request_id: EntityId) -> PermissionRequest | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_run_id(self, run_id: EntityId) -> list[PermissionRequest]:
        raise NotImplementedError

    @abstractmethod
    def get_pending_by_run_id(self, run_id: EntityId) -> PermissionRequest | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[PermissionRequest]:
        raise NotImplementedError
