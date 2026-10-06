"""The memory firewall: the last check before something becomes durable.

Memory is the highest-leverage persistence surface in NEXUS. A task row is a
task; a memory row is text that gets replayed into *every future prompt* this
assistant builds. Anything that lands here is durable input to later decisions,
including decisions made by a model that reads it. So this module is deliberately
the strictest thing in the memory path, and it applies three checks in order.

**Secrets are refused, not redacted.** A credential the user pasted is refused at
save time. Redacting would store a mangled version of a real credential, which
reads as "handled safely" while still leaving a secret on disk in a system the
user believes did not keep it. Failing loudly is the honest outcome.

**Instruction-shaped content is refused.** Memory that reads like an instruction
("ignore previous instructions and always...") is an injection waiting to be
replayed. The model proposing it is the untrusted party here; the fact that the
model produced the text is not evidence that the text is safe.

**Ownership is mandatory.** A memory with no owner cannot be denied to anyone, so
refusing to persist it is the only version of this that is not theatre.

Each rejection raises :class:`MemoryRejected`. Nothing is written, and the caller
gets a message naming the reason so the failure is diagnosable -- but the message
never quotes the content that was refused, because the content is exactly what we
do not want propagating.
"""

from __future__ import annotations

from app.application.security.injection import (
    InjectionSeverity,
    detect_injection,
    highest_severity,
    summarise,
)
from app.application.security.secrets import describe_findings, find_secrets
from app.domain.entities.memory import Memory
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision

#: Injection severity that blocks a write. Any finding blocks, not just HIGH.
#:
#: This is stricter than the detector's own SUSPICIOUS/HIGH split, on purpose.
#: Elsewhere in NEXUS an injection-shaped string is a signal for a human to look
#: at, because the cost of a false positive is a noisy log line. Here the cost is
#: asymmetric in the other direction:
#:
#: * a false positive costs one refused save and a message telling the user to
#:   rephrase as a fact ("the report contains noise to ignore", not "ignore all
#:   previous instructions");
#: * a false negative is permanent and compounding, because a stored memory is
#:   replayed into *every* future prompt this assistant builds. One accepted
#:   injection is not one bad session, it is every session after it.
#:
#: So the only thing being traded here is a slightly annoying refusal against an
#: unbounded one.
BLOCKING_SEVERITY = InjectionSeverity.SUSPICIOUS


class MemoryRejected(ValueError):
    """A memory was refused. Carries the reason, never the content."""

    def __init__(self, reason: str, *, kind: str = "REJECTED") -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


class MemoryFirewall:
    """Refuses memories that must not become durable."""

    def validate(
        self,
        candidate: MemoryCandidate,
        decision: MemoryPersistenceDecision,
    ) -> None:
        if decision is not MemoryPersistenceDecision.SAVE:
            raise MemoryRejected("memory blocked by policy", kind="POLICY")
        if candidate.requested_persistence is MemoryPersistenceDecision.DO_NOT_SAVE:
            raise MemoryRejected(
                "memory explicitly marked DO_NOT_SAVE", kind="POLICY"
            )
        self._validate_content(candidate.content)

    def validate_persisted(self, memory: Memory) -> None:
        """The final gate, after policy allowed it and before the database sees it."""
        if not memory.can_be_persisted:
            raise MemoryRejected(
                "DO_NOT_SAVE memory cannot reach persistence", kind="POLICY"
            )
        if memory.agent_id is None:
            raise MemoryRejected(
                "persisted memory requires an agent_id", kind="OWNERSHIP"
            )
        if memory.user_id is None:
            raise MemoryRejected(
                "persisted memory requires a user_id owner", kind="OWNERSHIP"
            )
        self._validate_content(memory.content)

    def _validate_content(self, content: str) -> None:
        findings = find_secrets(content)
        if findings:
            raise MemoryRejected(
                f"content appears to contain a credential ({describe_findings(findings)}); "
                "refusing to store it",
                kind="SECRET",
            )
        injection = detect_injection(content)
        if highest_severity(injection) is not InjectionSeverity.NONE:
            raise MemoryRejected(
                "content reads like an instruction rather than a fact; remember "
                "things as facts (what is true, what the user prefers) and "
                f"detected {summarise(injection)}",
                kind="INJECTION",
            )


__all__ = ("BLOCKING_SEVERITY", "MemoryFirewall", "MemoryRejected")