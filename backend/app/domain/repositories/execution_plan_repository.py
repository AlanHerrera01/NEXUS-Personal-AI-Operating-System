from abc import ABC, abstractmethod

from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.value_objects.entity_id import EntityId


class ExecutionPlanRepository(ABC):
    @abstractmethod
    def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, plan_id: EntityId) -> ExecutionPlan | None:
        raise NotImplementedError
