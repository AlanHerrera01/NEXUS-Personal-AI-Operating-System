from enum import StrEnum


class MemorySource(StrEnum):
    USER_EXPLICIT = "USER_EXPLICIT"
    AGENT_ACTION = "AGENT_ACTION"
    CONVERSATION = "CONVERSATION"
    SYSTEM = "SYSTEM"
