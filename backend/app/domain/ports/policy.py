from abc import ABC, abstractmethod

from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class Policy(ABC):
    """Deterministic security policy that evaluates trust context."""

    @abstractmethod
    def evaluate(self, context: TrustContext) -> PolicyResult:
        """Evaluate the context and return a policy decision."""
        raise NotImplementedError

    @property
    @abstractmethod
    def policy_id(self) -> str:
        """Unique identifier for this policy."""
        raise NotImplementedError

    @property
    @abstractmethod
    def priority(self) -> int:
        """Policy priority (higher = more restrictive). DENY policies should have highest priority."""
        raise NotImplementedError
