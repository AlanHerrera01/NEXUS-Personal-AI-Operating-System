from abc import ABC, abstractmethod

from app.domain.ports.tool import ToolDefinition
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.trust_evaluation import TrustEvaluation


class TrustEngine(ABC):
    @abstractmethod
    def evaluate(
        self,
        tool: ToolDefinition,
        user_id: EntityId | None,
        agent_id: EntityId,
        agent_run_id: EntityId,
        arguments: dict,
    ) -> TrustEvaluation:
        raise NotImplementedError
