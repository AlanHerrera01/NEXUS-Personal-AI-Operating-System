from enum import StrEnum


class RuntimeState(StrEnum):
    """Lifecycle of a sandboxed execution environment.

    Deliberately separate from ``AgentRunStatus``: a run may be EXECUTING while
    its runtime is READY, and a runtime can be EXPIRED while the run is
    COMPLETED. Collapsing them would make "the agent is busy" and "the sandbox
    exists" indistinguishable.
    """

    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES

    @property
    def accepts_execution(self) -> bool:
        return self in _EXECUTABLE_STATES


_TERMINAL_STATES = frozenset(
    {
        RuntimeState.FAILED,
        RuntimeState.STOPPED,
        RuntimeState.EXPIRED,
        RuntimeState.BLOCKED,
    }
)

_EXECUTABLE_STATES = frozenset({RuntimeState.READY, RuntimeState.RUNNING})
