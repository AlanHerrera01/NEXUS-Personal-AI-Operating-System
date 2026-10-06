from enum import StrEnum


class PlanStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
