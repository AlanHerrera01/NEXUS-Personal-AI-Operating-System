from app.application.security.audit import NullAuditLog, SecurityAuditLog
from app.domain.value_objects.runtime_event_type import AuthorizationEventType


def test_audit_records_the_policy_that_made_the_decision() -> None:
    audit = SecurityAuditLog()

    entry = audit.record(
        AuthorizationEventType.TOOL_ALLOWED,
        tool_name="docker.logs",
        decision="ALLOW",
        risk_level="LOW",
        policy_id="default_allow",
        reason="read-only tool",
    )

    assert entry.policy_id == "default_allow"
    assert entry.as_dict()["policy_id"] == "default_allow"
    logger_entry = audit.entries()[0]
    assert logger_entry.policy_id == "default_allow"


def test_null_audit_accepts_the_same_fields_as_the_real_log() -> None:
    audit = NullAuditLog()

    entry = audit.record(
        AuthorizationEventType.TOOL_DENIED,
        tool_name="docker.logs",
        policy_id="sensitive_resource",
        reason="denied",
    )

    assert entry.policy_id == "sensitive_resource"
