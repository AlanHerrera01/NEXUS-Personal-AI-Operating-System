from app.domain.entities.agent_run import AgentRun
from app.domain.ports.memory_retriever import MemoryRetriever
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.value_objects.entity_id import EntityId


class AgentContextBuilder:
    """Assembles the dictionary the brain reasons over.

    Memories are fetched with the run's owner, not just its agent. The agent is
    chosen by the model; the owner is chosen by the caller and comes from the
    resolved identity. Filtering on agent alone meant any run could pull any
    memory belonging to that agent regardless of who asked.
    """

    def __init__(self, memory_retriever: MemoryRetriever | None, tool_registry: ToolRegistry) -> None:
        self.memory_retriever = memory_retriever
        self.tool_registry = tool_registry

    def build(
        self,
        agent_run: AgentRun,
        available_tools: list | None = None,
        *,
        user_id: EntityId | None = None,
    ) -> dict:
        memories = []
        if self.memory_retriever is not None:
            if user_id is None:
                # Fail closed rather than retrieve unscoped. Falling back to "no
                # owner filter" here would quietly restore the cross-user read
                # this signature exists to prevent.
                raise ValueError(
                    "memory retrieval requires the acting user's identity"
                )
            memories = self.memory_retriever.search(
                agent_run.agent_id, user_id, agent_run.user_request, limit=5
            )
        tools = available_tools if available_tools is not None else self.tool_registry.definitions()
        return {
            "agent_id": agent_run.agent_id,
            "agent_run_id": agent_run.id,
            "user_request": agent_run.user_request,
            "relevant_memories": memories,
            "available_tools": tools,
            "observations": [],
        }