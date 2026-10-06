from app.domain.entities.permission import Permission
from app.domain.ports.policy import Policy
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class PermissionPolicy(Policy):
    """Defer to an explicit stored decision about a skill/action.

    The semantics were wrong in a way worth recording, because the fix looks like
    a no-op. This policy used to ask "is there an ALLOW row?" and deny when the
    answer was no. Combined with a registry that only builds the policy when a
    permission repository is present, that produced two bad states at once:

    * with a repository wired, *every* action without a manually-created ALLOW row
      was denied, including plain read-only ones -- the system was unusable rather
      than secure;
    * with no repository (how it was actually wired), the policy was never built,
      so ``POST /permissions`` wrote rows that no decision ever consulted. Grants
      were decorative.

    So absence of a row now means "nobody has expressed an opinion", and this
    policy abstains. An explicit DENY row is still honoured immediately. The
    default-deny guarantee does not come from here; it comes from
    :class:`PolicyEngine`, which denies when no policy applies, and from the risk
    policies, which are what actually classify an action.

    A grant therefore narrows escalation rather than granting authority on its
    own: it can satisfy an ASK, but it cannot override a destructive-action DENY,
    because the engine short-circuits on DENY before any ALLOW is considered.
    """

    def __init__(self, permission_checker=None, permission_resolver=None) -> None:
        # ``permission_checker`` is the historical bool-shaped callback, kept so
        # callers that only have one still work. When it is the only thing
        # supplied, the semantics are the old ones and that is visible rather
        # than silently changed.
        self._permission_checker = permission_checker
        self._permission_resolver = permission_resolver

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if self._permission_resolver is not None:
            permission = self._permission_resolver(
                context.user_id,
                context.agent_id,
                context.skill_name,
                context.tool_name,
            )
            if permission is None:
                return PolicyResult.not_applicable(self.policy_id)
            if permission.effect is PermissionDecision.DENY:
                return PolicyResult.deny(
                    self.policy_id,
                    f"Permission denied for '{context.tool_name}'",
                )
            # An explicit ALLOW resolves the permission question and nothing
            # else. Lower-priority risk policies still run.
            return PolicyResult.allow(
                self.policy_id,
                f"Permission granted for '{context.tool_name}'",
            )

        if self._permission_checker is None:
            return PolicyResult.not_applicable(self.policy_id)

        if self._permission_checker(
            context.user_id,
            context.agent_id,
            context.skill_name,
            context.tool_name,
        ):
            return PolicyResult.allow(
                self.policy_id, f"Permission granted for '{context.tool_name}'"
            )
        return PolicyResult.deny(
            self.policy_id, f"Permission denied for '{context.tool_name}'"
        )

    @property
    def policy_id(self) -> str:
        return "permission"

    @property
    def priority(self) -> int:
        # Above the risk policies so a stored opinion is recorded against the
        # decision, and below the destructive/sensitive policies so those can
        # short-circuit with a DENY first.
        return 80