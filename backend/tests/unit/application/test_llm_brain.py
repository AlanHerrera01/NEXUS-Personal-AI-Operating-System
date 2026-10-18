"""The model-backed brain.

What is under test is not "does it call the provider" but the two properties that
decide whether an LLM in the agent loop is safe to ship: a reply the brain cannot
parse becomes an answer rather than an action, and a model failure becomes a
message that names the problem rather than a fabricated reply. Both are the
failure modes the previous brain had -- it answered from a template and never
consulted a model at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.application.agents.llm_brain import LLMAgentBrain
from app.application.llm.llm_service import LLMService
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentDecisionType
from app.domain.ports.llm_errors import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMUnavailableError,
)
from app.domain.ports.llm_provider import LLMProvider, LLMRequest, LLMResponse
from app.domain.ports.tool import ToolDefinition, ToolObservation
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel


class FakeProvider(LLMProvider):
    """Records what it was asked and replies with a canned content or error."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMResponse(content=self.reply, model="fake-model")


def build_brain(reply: str = "", error: Exception | None = None) -> tuple[LLMAgentBrain, FakeProvider]:
    provider = FakeProvider(reply, error)
    return LLMAgentBrain(LLMService(provider)), provider


def run(request: str = "hOLA") -> AgentRun:
    return AgentRun(agent_id=EntityId.new(), user_request=request)


def tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="tasks.create",
            description="Crea una tarea.",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            skill_name="tasks",
            risk_level=RiskLevel.LOW,
        )
    ]


def send(brain: LLMAgentBrain, context: dict[str, Any] | None = None):
    return brain.decide(run(), context or {}, tools())


# -- the reply is used as an answer -------------------------------------------


async def test_prose_is_returned_as_a_final_answer() -> None:
    brain, _ = build_brain("¡Hola! ¿En qué te ayudo?")

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.FINAL
    assert decision.response == "¡Hola! ¿En qué te ayudo?"


async def test_a_json_final_decision_carries_its_response() -> None:
    brain, _ = build_brain('{"decision": "FINAL", "response": "Son las 14:05."}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.FINAL
    assert decision.response == "Son las 14:05."


async def test_a_fenced_json_decision_is_read() -> None:
    brain, _ = build_brain('```json\n{"decision": "FINAL", "response": "Listo"}\n```')

    decision = await send(brain)

    assert decision.response == "Listo"


async def test_json_surrounded_by_prose_is_still_read() -> None:
    brain, _ = build_brain('Claro:\n{"decision": "FINAL", "response": "Hecho"}\nEspero que sirva.')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.FINAL
    assert decision.response == "Hecho"


async def test_malformed_json_is_answered_verbatim_rather_than_dropped() -> None:
    brain, _ = build_brain('{"decision": "FINAL", "response": "cortada')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.FINAL
    assert decision.response == '{"decision": "FINAL", "response": "cortada'


# -- a tool call needs a decision, not a resemblance --------------------------


async def test_a_tool_call_decision_becomes_a_tool_call() -> None:
    brain, _ = build_brain(
        '{"decision": "TOOL_CALL", "tool_name": "tasks.create", "arguments": {"title": "Comprar"}}'
    )

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.TOOL_CALL
    assert decision.tool_name == "tasks.create"
    assert decision.arguments == {"title": "Comprar"}


async def test_json_without_a_decision_is_refused_rather_than_guessed() -> None:
    # A tool name in a JSON blob is not a decision to call it. Treating it as one
    # would let any stray object the model emits start an execution.
    brain, _ = build_brain('{"tool_name": "tasks.create", "arguments": {"title": "x"}}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ERROR


async def test_a_tool_call_without_a_name_is_refused() -> None:
    brain, _ = build_brain('{"decision": "TOOL_CALL", "arguments": {}}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ERROR


async def test_a_final_decision_without_a_response_is_refused() -> None:
    brain, _ = build_brain('{"decision": "FINAL"}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ERROR


async def test_an_unknown_decision_is_refused() -> None:
    brain, _ = build_brain('{"decision": "DANCE"}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ERROR
    assert decision.error is not None and "DANCE" in decision.error


async def test_an_ask_user_decision_carries_the_question() -> None:
    brain, _ = build_brain('{"decision": "ASK_USER", "question": "¿Qué fichero?"}')

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ASK_USER
    assert decision.question == "¿Qué fichero?"


# -- the model is actually asked, with what it needs --------------------------


async def test_the_prompt_carries_the_request_the_tools_and_the_schema() -> None:
    brain, provider = build_brain('{"decision": "FINAL", "response": "ok"}')

    await send(brain)

    assert len(provider.requests) == 1
    messages = provider.requests[0].messages
    system, user = messages[0], messages[1]
    assert "tasks.create" in system.content
    assert "Crea una tarea." in system.content
    assert "title" in system.content
    assert "hOLA" in user.content


async def test_observations_are_shown_back_to_the_model() -> None:
    brain, provider = build_brain('{"decision": "FINAL", "response": "Hecho"}')
    context = {
        "observations": [
            ToolObservation(tool_name="tasks.create", success=True, output={"title": "Comprar"})
        ]
    }

    await send(brain, context)

    user = provider.requests[0].messages[1]
    assert "tasks.create" in user.content
    assert "Comprar" in user.content


async def test_relevant_memories_are_shown_back_to_the_model() -> None:
    brain, provider = build_brain('{"decision": "FINAL", "response": "ok"}')

    class Memory:
        content = "El usuario prefiere respuestas cortas."

    await send(brain, {"relevant_memories": [Memory()]})

    user = provider.requests[0].messages[1]
    assert "respuestas cortas" in user.content


async def test_a_deployment_without_tools_says_so_instead_of_listing_none() -> None:
    brain, provider = build_brain('{"decision": "FINAL", "response": "ok"}')

    await brain.decide(run(), {}, [])

    system = provider.requests[0].messages[0]
    assert "No tienes herramientas disponibles" in system.content


# -- failures name the problem ------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LLMAuthenticationError("NEBIUS_API_KEY is not configured"), "no está configurado"),
        (LLMUnavailableError("boom"), "no está disponible"),
        (LLMRateLimitError("429"), "límite de uso"),
    ],
)
async def test_a_provider_failure_becomes_an_error_decision(error: Exception, expected: str) -> None:
    brain, _ = build_brain(error=error)

    decision = await send(brain)

    assert decision.decision_type is AgentDecisionType.ERROR
    assert decision.error is not None and expected in decision.error
    # Never a response: an answer here would be indistinguishable from one.
    assert decision.response is None
