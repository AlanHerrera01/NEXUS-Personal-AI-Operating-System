from app.domain.entities.runtime_session import RuntimeSession
from app.domain.value_objects.runtime_state import RuntimeState


class InvalidRuntimeTransition(ValueError):
    """Raised when a runtime is asked to move to a state it cannot reach."""


class RuntimeStateService:
    """Owns the legal RuntimeSession state graph.

    Mirrors the role of ``AgentRunStateService`` but for a separate machine:
    a run's status and a runtime's status are independent, and neither may set
    the other's field.
    """

    _allowed = {
        RuntimeState.CREATED: {RuntimeState.INITIALIZING, RuntimeState.BLOCKED, RuntimeState.FAILED},
        RuntimeState.INITIALIZING: {
            RuntimeState.READY,
            RuntimeState.FAILED,
            RuntimeState.BLOCKED,
            RuntimeState.EXPIRED,
        },
        RuntimeState.READY: {
            RuntimeState.RUNNING,
            RuntimeState.STOPPING,
            RuntimeState.EXPIRED,
            RuntimeState.FAILED,
            RuntimeState.BLOCKED,
        },
        RuntimeState.RUNNING: {
            RuntimeState.READY,
            RuntimeState.WAITING,
            RuntimeState.STOPPING,
            RuntimeState.FAILED,
            RuntimeState.EXPIRED,
            RuntimeState.BLOCKED,
        },
        RuntimeState.WAITING: {
            RuntimeState.READY,
            RuntimeState.RUNNING,
            RuntimeState.STOPPING,
            RuntimeState.EXPIRED,
            RuntimeState.FAILED,
            RuntimeState.BLOCKED,
        },
        RuntimeState.STOPPING: {RuntimeState.STOPPED, RuntimeState.FAILED},
        RuntimeState.STOPPED: {RuntimeState.INITIALIZING},
        RuntimeState.EXPIRED: set(),
        RuntimeState.FAILED: set(),
        RuntimeState.BLOCKED: set(),
    }

    def transition(self, session: RuntimeSession, target: RuntimeState) -> RuntimeSession:
        if target is not session.state and target not in self._allowed[session.state]:
            raise InvalidRuntimeTransition(
                f"invalid runtime transition: {session.state} -> {target}"
            )
        session.set_state(target)
        return session
