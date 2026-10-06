from enum import StrEnum


class NetworkMode(StrEnum):
    """Egress posture for a runtime. DENY is the default and the fallback."""

    DENY = "DENY"
    RESTRICTED = "RESTRICTED"
    ALLOW = "ALLOW"
