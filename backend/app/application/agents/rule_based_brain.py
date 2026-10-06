from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentBrain, AgentDecision


class RuleBasedAgentBrain(AgentBrain):
    """Local, no-credit brain used until a verified LLM decision adapter is selected."""

    async def decide(self, agent_run: AgentRun, context: dict, tool_definitions: list) -> AgentDecision:
        if context.get("observations"):
            observation = context["observations"][-1]
            if observation.success:
                return AgentDecision.final("Listo. La herramienta confirmó la acción.")
            return AgentDecision.final("La herramienta no pudo completar la acción.")
        request = agent_run.user_request.lower()
        if "crear una tarea" in request or "crea una tarea" in request:
            title = agent_run.user_request.split("tarea", 1)[-1].strip(" :.") or "Nueva tarea"
            return AgentDecision.tool_call("task.create", {"title": title})
        if "listar tareas" in request or "qué tareas" in request:
            return AgentDecision.tool_call("task.list", {})
        return AgentDecision.final(f"NEXUS recibió tu solicitud: {agent_run.user_request}")
