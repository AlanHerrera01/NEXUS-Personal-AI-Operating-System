import re

from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.ports.memory_policy import MemoryDecision, MemoryPolicy
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_source import MemorySource


class DeterministicMemoryPolicy(MemoryPolicy):
    _do_not_save = re.compile(r"no\s+guardes|no\s+lo\s+guardes|don't\s+save|do\s+not\s+save", re.IGNORECASE)
    _explicit_save = re.compile(r"recuerda|guarda|remember|save\s+this", re.IGNORECASE)
    _sensitive = re.compile(r"password|contrase(?:n|ñ)a|api\s*key|token|secret|private\s+key|ssh", re.IGNORECASE)

    def evaluate(self, candidate: MemoryCandidate) -> MemoryDecision:
        instruction = f"{candidate.user_instruction} {candidate.content}".strip()
        if candidate.requested_persistence is MemoryPersistenceDecision.DO_NOT_SAVE:
            return MemoryDecision(MemoryPersistenceDecision.DO_NOT_SAVE, "persistence was explicitly disabled")
        if self._do_not_save.search(instruction):
            return MemoryDecision(MemoryPersistenceDecision.DO_NOT_SAVE, "explicit opt-out detected")
        if self._sensitive.search(instruction):
            return MemoryDecision(MemoryPersistenceDecision.DO_NOT_SAVE, "sensitive content is not eligible")
        if len(candidate.content.strip()) < 8:
            return MemoryDecision(MemoryPersistenceDecision.DO_NOT_SAVE, "content is not relevant enough")
        if candidate.source is MemorySource.USER_EXPLICIT or self._explicit_save.search(candidate.user_instruction):
            return MemoryDecision(MemoryPersistenceDecision.SAVE, "explicit memory request accepted")
        return MemoryDecision(MemoryPersistenceDecision.DO_NOT_SAVE, "automatic persistence is disabled")
