from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel


@dataclass
class PermissionRequest:
    agent_run_id: EntityId
    tool_name: str
    skill_name: str
    reason: str
    risk_level: RiskLevel
    arguments_summary: dict[str, Any] = field(default_factory=dict)
    id: EntityId = field(default_factory=EntityId.new)
    #: Who the request was raised on behalf of. Stored rather than inferred so an
    #: approval cannot be resolved against a different user than the one who
    #: caused the request. Optional because requests predate this field and a
    #: missing owner must not be read as "owned by whoever asks next".
    user_id: EntityId | None = None
    status: PermissionRequestStatus = PermissionRequestStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=lambda: utc_now() + timedelta(minutes=5))
    updated_at: datetime = field(default_factory=utc_now)
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_text(self.tool_name, "tool_name")
        require_text(self.skill_name, "skill_name")
        require_text(self.reason, "reason")
        # Ensure expires_at is timezone-aware
        if self.expires_at.tzinfo is None:
            self.expires_at = self.expires_at.replace(tzinfo=timezone.utc)

    def approve(self) -> None:
        if self.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot approve request in status: {self.status}")
        self.status = PermissionRequestStatus.APPROVED
        self.updated_at = utc_now()

    def reject(self) -> None:
        if self.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot reject request in status: {self.status}")
        self.status = PermissionRequestStatus.REJECTED
        self.updated_at = utc_now()

    def expire(self) -> None:
        if self.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot expire request in status: {self.status}")
        self.status = PermissionRequestStatus.EXPIRED
        self.updated_at = utc_now()

    def cancel(self) -> None:
        if self.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot cancel request in status: {self.status}")
        self.status = PermissionRequestStatus.CANCELLED
        self.updated_at = utc_now()

    def is_expired(self) -> bool:
        # Ensure both datetimes are timezone-aware for comparison
        now = utc_now()
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    def is_consumable(self) -> bool:
        return (
            self.status == PermissionRequestStatus.APPROVED
            and not self.is_expired()
            and self.consumed_at is None
        )

    def consume(self) -> None:
        """Single-use guard: an approval may authorize exactly one execution."""
        if not self.is_consumable():
            raise ValueError(f"Request is not consumable: {self.status}")
        self.consumed_at = utc_now()
        self.updated_at = self.consumed_at
