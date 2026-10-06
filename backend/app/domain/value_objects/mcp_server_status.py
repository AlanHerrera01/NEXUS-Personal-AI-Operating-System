from enum import StrEnum


class MCPServerStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    ERROR = "ERROR"
    DISABLED = "DISABLED"
