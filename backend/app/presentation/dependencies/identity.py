"""Who a request belongs to.

NEXUS has no authentication layer, so there is nothing that can honestly answer
"who is calling" -- and the existing routes do not pretend otherwise, they accept
a literal ``default-user-id`` placeholder.

Always-On cannot copy that, because ownership is load-bearing here: it is the
only thing separating one user's jobs from another's, and it is stored in a
``uuid`` column. So rather than invent a fake identity, this module pins a single
stable UUID as *the* local user and says so plainly.

Two consequences, both deliberate:

* every job, execution and rule on a deployment without auth belongs to the same
  owner. That is not a security control and must not be described as one -- it is
  the honest consequence of a single-operator deployment.
* there is no request header, query parameter or token that can change the
  owner. Accepting one would look like access control while being trivially
  forged by anyone who can reach the API.

When real authentication lands, this module is the single place that changes.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from fastapi import Depends

from app.domain.value_objects.entity_id import EntityId

#: Stable namespace so the default owner is reproducible rather than a literal
#: typed into three different modules.
LOCAL_USER_NAMESPACE = UUID("6e657875-7320-7573-6572-000000000000")

#: The single local operator's id. Deterministic: every process and every
#: deployment of this codebase computes the same value, so rows created by one
#: process are visible to the next.
LOCAL_USER_ID = uuid5(LOCAL_USER_NAMESPACE, "default-user-id")


def current_user_id() -> EntityId:
    """The acting user for this request.

    A dependency rather than a module constant at every call site, so that adding
    real authentication later means changing this function -- not auditing every
    route for places that hardcoded the owner.

    It is deliberately *not* overridable. It reads no header, query parameter or
    body field, because with no authentication behind it, accepting a caller-supplied
    identity would be access control in appearance only: anything that could reach
    the API could claim any owner. The absence of that knob is the control.
    """
    return EntityId(LOCAL_USER_ID)