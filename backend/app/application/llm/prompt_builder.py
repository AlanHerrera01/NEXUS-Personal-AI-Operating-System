from app.domain.ports.llm_provider import LLMMessage, LLMMessageRole


NEXUS_SYSTEM_PROMPT = (
    "NEXUS is a personal AI operating system. "
    "It assists the user, uses only authorized context, and follows system permissions. "
    "NEXUS must not claim actions it did not execute, invent unavailable information, "
    "or decide permissions by itself. Real actions are controlled by the application."
)


class PromptBuilder:
    def build(self, user_message: str) -> tuple[LLMMessage, ...]:
        if not user_message.strip():
            raise ValueError("user message must not be empty")
        return (
            LLMMessage(LLMMessageRole.SYSTEM, NEXUS_SYSTEM_PROMPT),
            LLMMessage(LLMMessageRole.USER, user_message),
        )
