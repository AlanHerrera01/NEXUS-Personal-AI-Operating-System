from dataclasses import dataclass

from app.application.memory.firewall import MemoryFirewall
from app.domain.entities.memory import Memory
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.ports.memory_policy import MemoryDecision, MemoryPolicy
from app.domain.repositories.memory_repository import MemoryRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_type import MemoryType


@dataclass(frozen=True)
class MemoryEvaluation:
    decision: MemoryDecision
    memory: Memory | None = None


class MemoryService:
    """Reads and writes memories on behalf of one user.

    Every method takes ``user_id`` and passes it to the repository. The service
    does not trust its callers to filter; it is the layer that knows the owner,
    so it is the layer that applies it. A service method without a user would be a
    method that returns whatever it finds.
    """

    def __init__(self, repository: MemoryRepository, policy: MemoryPolicy, firewall: MemoryFirewall) -> None:
        self.repository = repository
        self.policy = policy
        self.firewall = firewall

    def create_memory_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        return candidate

    def evaluate_memory(self, candidate: MemoryCandidate) -> MemoryEvaluation:
        decision = self.policy.evaluate(candidate)
        if decision.persistence is not MemoryPersistenceDecision.SAVE:
            return MemoryEvaluation(decision)
        self.firewall.validate(candidate, decision.persistence)
        return MemoryEvaluation(decision, candidate.to_memory(decision.persistence))

    def save_memory(self, candidate: MemoryCandidate) -> MemoryEvaluation:
        evaluation = self.evaluate_memory(candidate)
        if evaluation.memory is None:
            return evaluation
        self.firewall.validate_persisted(evaluation.memory)
        return MemoryEvaluation(evaluation.decision, self.repository.save(evaluation.memory))

    def get_memory(
        self, memory_id: EntityId, agent_id: EntityId, user_id: EntityId
    ) -> Memory | None:
        memory = self.repository.get_by_id(memory_id, user_id)
        # The agent check is kept even though the repository now filters by owner:
        # a memory can be owned by a user but belong to a different agent, and the
        # agent boundary is a separate question from the ownership one.
        if memory is None or memory.agent_id != agent_id:
            return None
        return memory

    def list_memories(
        self, agent_id: EntityId, user_id: EntityId, limit: int = 100
    ) -> list[Memory]:
        return self.repository.list_by_agent(agent_id, user_id, limit)

    def retrieve_memories(
        self,
        agent_id: EntityId,
        user_id: EntityId,
        query: str,
        limit: int = 10,
        memory_types: set[MemoryType] | None = None,
    ) -> list[Memory]:
        return self.repository.search(agent_id, user_id, query, limit, memory_types)

    def delete_memory(
        self, memory_id: EntityId, agent_id: EntityId, user_id: EntityId
    ) -> bool:
        return self.repository.delete(memory_id, agent_id, user_id)

    def clear_memories(self, agent_id: EntityId, user_id: EntityId) -> int:
        return self.repository.delete_by_agent(agent_id, user_id)
