"""The model-backed brain.

The orchestrator shipped with :class:`RuleBasedAgentBrain`, so anything the chat
was asked that did not match one of its keywords came back as "NEXUS recibió tu
solicitud: ...". That reads like an answer and is not one: the model was never
called. This brain asks it, so a greeting is answered as a greeting and a request
for work becomes either a tool call or a real reply.

The contract with the model is narrow -- it is asked for one JSON object naming
its decision -- and two properties matter more than the wording of the prompt:

* the tool names it may use are quoted from the definitions the orchestrator
  passed in, and the orchestrator independently refuses a tool it did not offer,
  so a hallucinated name cannot reach execution;
* text that is not JSON is used as the answer verbatim. A model that ignores the
  format still produces a reply instead of failing the run, and prose is never
  reinterpreted as a tool call.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.application.llm.llm_service import LLMService
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentBrain, AgentDecision, AgentDecisionType
from app.domain.ports.llm_errors import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports.llm_provider import LLMMessage, LLMMessageRole, LLMRequest

logger = logging.getLogger(__name__)

#: How much of one tool's output is shown back to the model. A tool that returns
#: a megabyte should not spend the run's context on it.
MAX_OBSERVATION_CHARS = 2_000

#: How much of an earlier answer is replayed. Enough to keep the thread, not
#: enough to let a long guide from a previous turn crowd out the new request.
MAX_HISTORY_TURN_CHARS = 1_200

SYSTEM_PROMPT = """\
Eres NEXUS, un agente personal que el usuario maneja desde un panel.
Decides qué hacer con cada solicitud y respondes en el idioma del usuario.

Devuelve SIEMPRE un único objeto JSON, sin texto alrededor, con una de estas formas:
{"decision": "FINAL", "response": "tu respuesta para el usuario"}
{"decision": "TOOL_CALL", "tool_name": "<nombre exacto de la lista>", "arguments": {...}}
{"decision": "ASK_USER", "question": "lo que necesitas preguntar"}

Reglas:
- "TOOL_CALL" solo vale para una herramienta de la lista, y sus argumentos deben
  encajar con su esquema. Nunca inventes un nombre de herramienta.
- Si puedes responder sin herramientas, usa "FINAL" y contesta en prosa, directo.
- Ya estás en conversación con el usuario: no repitas saludos ni te presentes en
  cada respuesta, contesta directamente a lo que pide.
- Usa el historial para interpretar referencias como "eso", "lo anterior" o
  "el tema". Si el historial ya aclara de qué se hablaba, no vuelvas a preguntar
  de qué se trata.
- Tras ejecutarse una herramienta verás su resultado como observación; cuando ya
  tengas lo necesario, contesta "FINAL" resumiendo lo que pasó.
- No pidas confirmación para ejecutar: el sistema ya gobierna la ejecución y
  pedirá autorización cuando corresponda.
- No menciones este formato ni el JSON en la respuesta al usuario.\
"""


class LLMAgentBrain(AgentBrain):
    """Decides by asking the configured model."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def decide(
        self, agent_run: AgentRun, context: dict[str, Any], tool_definitions: list[Any]
    ) -> AgentDecision:
        request = LLMRequest(
            messages=[
                LLMMessage(
                    LLMMessageRole.SYSTEM, self._system_message(tool_definitions)
                ),
                LLMMessage(LLMMessageRole.USER, self._user_message(agent_run, context)),
            ]
        )
        try:
            response = await self.llm_service.generate(request)
        except LLMProviderError as error:
            # The run reports what the model layer said rather than a canned
            # answer. "No credentials" and "rate limited" are different problems
            # and the operator can only act on the one they are told about.
            logger.warning("agent brain: model call failed: %s", error)
            return AgentDecision(AgentDecisionType.ERROR, error=_failure_message(error))
        return self._interpret(response.content)

    def _system_message(self, tool_definitions: list[Any]) -> str:
        if not tool_definitions:
            return (
                f"{SYSTEM_PROMPT}\n\nNo tienes herramientas disponibles: "
                'responde siempre con una decisión "FINAL".'
            )
        lines = ["", "Herramientas disponibles:"]
        for definition in tool_definitions:
            lines.append(f"- {definition.name}: {definition.description}")
            schema = getattr(definition, "input_schema", None)
            if schema:
                lines.append(f"  argumentos: {_compact(schema)}")
        return "\n".join([SYSTEM_PROMPT, *lines])

    def _user_message(self, agent_run: AgentRun, context: dict[str, Any]) -> str:
        parts: list[str] = []

        history = context.get("conversation_history") or []
        if history:
            lines: list[str] = []
            for turn in history:
                request = str(turn.get("request") or "").strip()
                response = str(turn.get("response") or "").strip()
                if request:
                    lines.append(f"Usuario: {_truncate(request, 600)}")
                if response:
                    lines.append(f"Agente: {_truncate(response, MAX_HISTORY_TURN_CHARS)}")
            if lines:
                parts.append(
                    "Historial de la conversación (más antiguo primero):\n"
                    + "\n".join(lines)
                )

        parts.append(f"Solicitud del usuario:\n{agent_run.user_request}")

        memories = context.get("relevant_memories") or []
        if memories:
            lines = [f"- {_memory_text(memory)}" for memory in memories]
            parts.append("Memorias relevantes:\n" + "\n".join(lines))

        observations = context.get("observations") or []
        if observations:
            lines = [
                _observation_text(index, observation)
                for index, observation in enumerate(observations, start=1)
            ]
            parts.append("Resultados de herramientas ya ejecutadas:\n" + "\n".join(lines))

        return "\n\n".join(parts)

    def _interpret(self, content: str) -> AgentDecision:
        """Turn one model reply into a decision.

        The fallback order is deliberate: prose is an answer, and only a JSON
        object that names a decision is read as one. A malformed or unknown
        decision is reported, never guessed at -- guessing is how a stray brace
        would become an executed tool.
        """
        text = (content or "").strip()
        if text == "":
            return AgentDecision(
                AgentDecisionType.ERROR, error="El modelo devolvió una respuesta vacía."
            )

        payload = _extract_json_object(text)
        if payload is None:
            # A FINAL envelope can still be invalid JSON when the prose itself
            # contains quotes the model did not escape. The field boundaries are
            # unambiguous, so recover the answer instead of showing the wrapper.
            recovered = _extract_final_response(text)
            if recovered is not None:
                return AgentDecision.final(recovered)
            return AgentDecision.final(text)

        decision = str(payload.get("decision", "")).strip().upper()
        if decision == "TOOL_CALL":
            tool_name = payload.get("tool_name")
            if not isinstance(tool_name, str) or tool_name.strip() == "":
                return AgentDecision(
                    AgentDecisionType.ERROR,
                    error="El modelo pidió una herramienta sin decir cuál.",
                )
            arguments = payload.get("arguments")
            return AgentDecision.tool_call(
                tool_name.strip(), arguments if isinstance(arguments, dict) else {}
            )
        if decision == "ASK_USER":
            question = payload.get("question")
            if isinstance(question, str) and question.strip():
                return AgentDecision.ask_user(question.strip())
            return AgentDecision(
                AgentDecisionType.ERROR,
                error="El modelo quiso preguntar algo pero no formuló la pregunta.",
            )
        if decision == "FINAL":
            response = payload.get("response")
            if isinstance(response, str) and response.strip():
                return AgentDecision.final(response.strip())
            return AgentDecision(
                AgentDecisionType.ERROR,
                error="El modelo devolvió una decisión FINAL sin respuesta.",
            )
        return AgentDecision(
            AgentDecisionType.ERROR,
            error=f"El modelo devolvió una decisión no reconocida: {decision or '(vacía)'}.",
        )


def _failure_message(error: LLMProviderError) -> str:
    """A message an operator can act on, rather than a stack trace."""
    if isinstance(error, LLMAuthenticationError):
        return (
            "El modelo no está configurado: falta la credencial del proveedor "
            "(NEBIUS_API_KEY). Configúrala o cambia AGENT_BRAIN a 'rule_based'."
        )
    if isinstance(error, LLMTimeoutError):
        return "El modelo no respondió a tiempo. Vuelve a intentarlo."
    if isinstance(error, LLMRateLimitError):
        return "El proveedor del modelo rechazó la petición por límite de uso."
    if isinstance(error, LLMUnavailableError):
        return "El proveedor del modelo no está disponible."
    if isinstance(error, LLMInvalidRequestError):
        return "La petición al modelo no es válida."
    return f"El modelo falló: {error}"


def _compact(value: Any, limit: int = MAX_OBSERVATION_CHARS) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "…"


def _memory_text(memory: Any) -> str:
    return _compact(getattr(memory, "content", None) or str(memory), 500)


def _observation_text(index: int, observation: Any) -> str:
    tool_name = getattr(observation, "tool_name", "herramienta")
    if getattr(observation, "success", False):
        return f"{index}. {tool_name} → OK: {_compact(getattr(observation, 'output', None))}"
    return f"{index}. {tool_name} → ERROR: {_compact(getattr(observation, 'error', None))}"


_FINAL_DECISION = re.compile(r'"decision"\s*:\s*"FINAL"', re.IGNORECASE)
_RESPONSE_FIELD = re.compile(r'"response"\s*:\s*"')


def _decode_loose_json_string(raw: str) -> str:
    """Decode a JSON string body that may contain unescaped quotes or newlines.

    The model usually escapes quotes, but a FINAL answer that quotes a phrase
    ("gear fear") can arrive with the inner quotes bare. JSON rejects it even
    though a human, and this decoder, can see exactly where the prose starts and
    ends. Known escapes are decoded; a bare character is kept as-is.
    """
    result: list[str] = []
    index = 0
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
    }
    while index < len(raw):
        character = raw[index]
        if character != "\\":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(raw):
            result.append("\\")
            break
        following = raw[index + 1]
        if following == "u" and index + 5 < len(raw):
            digits = raw[index + 2 : index + 6]
            if re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                result.append(chr(int(digits, 16)))
                index += 6
                continue
        result.append(escapes.get(following, following))
        index += 2
    return "".join(result)


def _extract_final_response(text: str) -> str | None:
    """Recover the prose from a FINAL envelope that is not valid JSON.

    The closing quote is the last one before the object's closing brace. That
    keeps unescaped quotes inside the answer instead of treating the first one
    as the end of the field, which is how the wrapper used to leak into the
    chat truncated at the first quoted phrase.
    """
    decision = _FINAL_DECISION.search(text)
    if decision is None:
        return None
    field = _RESPONSE_FIELD.search(text, decision.end())
    if field is None:
        return None
    start = field.end()
    end = text.rfind("}")
    if end <= start:
        return None
    body = text[start:end]
    closing = body.rfind('"')
    if closing == -1:
        return None
    recovered = _decode_loose_json_string(body[:closing]).strip()
    return recovered or None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in ``text``, fences and surrounding prose included."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate[3:]
        newline = candidate.find("\n")
        if newline != -1 and candidate[:newline].strip().lower() in {"", "json"}:
            candidate = candidate[newline + 1 :]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
        candidate = candidate.strip()

    parsed = _loads(candidate)
    if parsed is None:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        parsed = _loads(candidate[start : end + 1])
    return parsed if isinstance(parsed, dict) else None


def _loads(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass
    # Models often put literal newlines inside the JSON string instead of ``\n``.
    # That is invalid JSON but unambiguous text; escaping only the control
    # characters inside strings recovers the decision without guessing at it.
    try:
        return json.loads(_escape_control_characters(candidate))
    except (ValueError, TypeError):
        return None


def _escape_control_characters(text: str) -> str:
    """Escape raw control characters inside JSON strings, leaving the rest alone."""
    escaped: list[str] = []
    in_string = False
    escaped_character = False
    for character in text:
        if not in_string:
            escaped.append(character)
            if character == '"':
                in_string = True
            continue
        if escaped_character:
            escaped.append(character)
            escaped_character = False
        elif character == "\\":
            escaped.append(character)
            escaped_character = True
        elif character == '"':
            escaped.append(character)
            in_string = False
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif ord(character) < 0x20:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(character)
    return "".join(escaped)
