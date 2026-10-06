from abc import ABC, abstractmethod

from app.domain.entities.permission import Permission
from app.domain.value_objects.entity_id import EntityId


class PermissionRepository(ABC):
    @abstractmethod
    def save(self, permission: Permission) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, skill_name: str, action_name: str) -> Permission | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[Permission]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, permission_id: EntityId, user_id: EntityId) -> Permission | None:
        """One grant addressed by its own id, or None if absent or not ``user_id``'s."""
        raise NotImplementedError

    @abstractmethod
    def delete_by_id(self, permission_id: EntityId, user_id: EntityId) -> bool:
        """Revoke one grant by id. False if it did not exist or is not the caller's."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, user_id: EntityId, agent_id: EntityId, skill_name: str, action_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def check_permission(self, user_id: EntityId, agent_id: EntityId, skill_name: str, action_name: str) -> bool:
        """Check if a user/agent has permission for a specific skill/action."""
        raise NotImplementedError

    @abstractmethod
    def resolve(
        self,
        user_id: EntityId | None,
        agent_id: EntityId,
        skill_name: str,
        action_name: str,
    ) -> Permission | None:
        """The stored opinion about an action, whatever its effect, or None.

        Distinct from :meth:`check_permission` because the two answer different
        questions. ``check_permission`` asks "was this granted?" and answers with a
        bool, which cannot distinguish an explicit DENY row from no row at all.
        A policy needs that distinction: absence of a row means nobody has an
        opinion, and an explicit DENY means somebody refused.
        """
        raise NotImplementedError
