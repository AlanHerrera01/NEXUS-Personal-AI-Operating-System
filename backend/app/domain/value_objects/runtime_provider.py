from enum import StrEnum


class RuntimeProvider(StrEnum):
    """Which isolation technology backs an ``AgentRuntimePort`` implementation.

    The Domain only uses this for reporting and bookkeeping. It never switches
    behaviour on it, and it knows nothing about any provider's API.
    """

    OPENSHELL = "OPENSHELL"
    LOCAL = "LOCAL"
    IN_MEMORY = "IN_MEMORY"
