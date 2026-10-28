"""Single-operator identity protected by the application authentication gate."""
from __future__ import annotations

from uuid import UUID, uuid5

import hashlib
import hmac

from fastapi import HTTPException, Request

from app.config.settings import get_settings

from app.domain.value_objects.entity_id import EntityId

#: Stable namespace so the default owner is reproducible rather than a literal
#: typed into three different modules.
LOCAL_USER_NAMESPACE = UUID("6e657875-7320-7573-6572-000000000000")

#: The single local operator's id. Deterministic: every process and every
#: deployment of this codebase computes the same value, so rows created by one
#: process are visible to the next.
LOCAL_USER_ID = uuid5(LOCAL_USER_NAMESPACE, "default-user-id")


def require_authentication(request: Request) -> None:
    # Health exposes no user data. The webhook authenticates its own secret.
    if request.url.path in {"/health", "/api/v1/health", "/api/v1/events/trigger"}:
        return
    expected = get_settings().auth_token_hash
    if not expected:
        raise HTTPException(503, "Access is not configured. Run scripts/setup_local.py.")
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(actual, expected):
        raise HTTPException(401, "Invalid or missing access key.", headers={"WWW-Authenticate": "Bearer"})


def current_user_id() -> EntityId:
    """Stable single-operator owner; the application gate authenticates requests.

    Key rotation preserves ownership of existing data. This is not a multi-user
    account system, and callers cannot choose an owner through a header.
    """
    return EntityId(LOCAL_USER_ID)
