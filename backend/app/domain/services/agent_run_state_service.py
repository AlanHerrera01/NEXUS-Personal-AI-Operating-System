from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.agent_run_status import AgentRunStatus


class AgentRunStateService:
    _allowed_transitions = {
        AgentRunStatus.CREATED: {
            AgentRunStatus.CONTEXT_LOADING,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.CONTEXT_LOADING: {
            AgentRunStatus.PLANNING,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.PLANNING: {
            AgentRunStatus.WAITING_PERMISSION,
            AgentRunStatus.EXECUTING,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.WAITING_PERMISSION: {
            # EXECUTING is the approved-action path. PLANNING is the answered-
            # question path: a run that stopped to ask for missing detail goes
            # back to planning with the detail instead of executing anything.
            AgentRunStatus.PLANNING,
            AgentRunStatus.EXECUTING,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.EXECUTING: {
            AgentRunStatus.OBSERVING,
            AgentRunStatus.FAILED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.OBSERVING: {
            AgentRunStatus.PLANNING,
            AgentRunStatus.EXECUTING,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.COMPLETED: set(),
        AgentRunStatus.FAILED: set(),
        AgentRunStatus.BLOCKED: set(),
        AgentRunStatus.CANCELLED: set(),
    }

    def transition(self, agent_run: AgentRun, target: AgentRunStatus) -> AgentRun:
        if target not in self._allowed_transitions[agent_run.status]:
            raise ValueError(f"invalid agent run transition: {agent_run.status} -> {target}")
        agent_run.set_status(target)
        return agent_run
