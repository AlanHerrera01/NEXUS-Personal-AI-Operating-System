import logging
import time
from dataclasses import dataclass, field

from app.application.security.approval_service import ApprovalService
from app.application.security.audit import SecurityAuditLog
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.ports.agent_brain import AgentBrain, AgentDecisionType
from app.domain.ports.agent_runtime import (
    RuntimePolicyRejectedError,
    RuntimeUnavailableError,
)
from app.domain.ports.plan_validator import (
    PlanValidationResult,
    PlanValidatorPort,
    ProposedAction,
    ProposedPlan,
)
from app.domain.ports.tool import ToolContext, ToolDefinition
from app.domain.ports.tool_catalog import ToolCatalog
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.ports.trust_engine import TrustEngine
from app.domain.services.agent_run_state_service import AgentRunStateService
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.execution_authorization import (
    AuthorizationError,
    ExecutionAuthorization,
)
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.runtime_event_type import AuthorizationEventType

logger = logging.getLogger("nexus.agents.orchestrator")


@dataclass(frozen=True)
class AgentExecutionResult:
    run: AgentRun
    response: str | None = None
    question: str | None = None
    observations: list = field(default_factory=list)
    #: Why the Trust Engine escalated this action. Kept out of ``question`` so the
    #: prompt a human answers stays stable and comparable across tools.
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _GateOutcome:
    """Result of the single authorization path both entry points share."""

    #: The action, already persisted with its decision attached.
    action: AgentAction
    decision: PermissionDecision
    reason: str
    policy_id: str
    requires_confirmation: bool
    #: Set only when the decision is ALLOW. Carries the minted proof.
    authorization: ExecutionAuthorization | None = None


class AgentOrchestrator:
    """Controls the agent loop. Knows registries, never knows concrete skills."""

    def __init__(
        self,
        agent_brain: AgentBrain,
        context_builder,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        trust_engine: TrustEngine,
        agent_run_repository,
        agent_action_repository: AgentActionRepository,
        approval_service: ApprovalService | None = None,
        state_service: AgentRunStateService | None = None,
        tool_catalog: ToolCatalog | None = None,
        plan_validator: PlanValidatorPort | None = None,
        security_audit: SecurityAuditLog | None = None,
        max_iterations: int = 10,
        max_tool_calls: int = 10,
        max_permission_requests: int = 3,
        max_denied_actions: int = 5,
        max_runtime_seconds: float = 300.0,
        max_tracked_runs: int = 10_000,
    ) -> None:
        self.agent_brain = agent_brain
        self.context_builder = context_builder
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.trust_engine = trust_engine
        self.agent_run_repository = agent_run_repository
        self.agent_action_repository = agent_action_repository
        self.approval_service = approval_service
        self.state_service = state_service or AgentRunStateService()
        self.tool_catalog = tool_catalog
        # The Plan Validator runs before the Trust Engine, never instead of it.
        # It answers "is this well-formed and inside the run's namespace"; the
        # Trust Engine answers "is this allowed". A plan that fails validation
        # never reaches an authorization decision.
        self.plan_validator = plan_validator
        self.security_audit = security_audit
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.max_permission_requests = max_permission_requests
        self.max_denied_actions = max_denied_actions
        self.max_runtime_seconds = max_runtime_seconds
        self.max_tracked_runs = max_tracked_runs
        # Runaway guards are properties of the *run*, not of one call into
        # execute(). Keeping them per run is what stops a caller from simply
        # re-entering execute() to reset the budget.
        self._counters: dict[object, dict[str, int]] = {}
        self._deadlines: dict[object, float] = {}

    def _budget(self, run: AgentRun) -> dict[str, int]:
        """Counters for this run. Reset only when the run is genuinely new."""
        counters = self._counters.get(run.id)
        if counters is None:
            counters = {"tool_calls": 0, "permission_requests": 0, "denied_actions": 0}
            self._counters[run.id] = counters
            self._deadlines[run.id] = time.monotonic() + self.max_runtime_seconds
            self._evict_counters()
        return counters

    def _reset_budget(self, run: AgentRun) -> dict[str, int]:
        counters = {"tool_calls": 0, "permission_requests": 0, "denied_actions": 0}
        self._counters[run.id] = counters
        self._deadlines[run.id] = time.monotonic() + self.max_runtime_seconds
        self._evict_counters()
        return counters

    def _evict_counters(self) -> None:
        """Keep the budget table bounded.

        Without this the table grows once per run for the life of the process, so
        "start an agent run" is a slow memory-exhaustion primitive available to
        anyone who can reach the API. Finished runs are the cheapest to drop: a
        re-entered run whose counters were dropped starts from zero, so the
        oldest *live* entry is dropped instead, preferring the one closest to
        expiring. Dropping is fail-open on the budget and never on the decision,
        so the ceiling here is a memory bound, not an authorization decision.
        """
        if len(self._counters) <= self.max_tracked_runs:
            return
        ranked = sorted(self._deadlines.items(), key=lambda item: item[1])
        for run_id, _ in ranked[: len(self._counters) - self.max_tracked_runs]:
            self._counters.pop(run_id, None)
            self._deadlines.pop(run_id, None)

    def _runtime_exhausted(self, run: AgentRun) -> bool:
        deadline = self._deadlines.get(run.id)
        if deadline is None:
            return False
        return time.monotonic() > deadline

    def _begin_turn(self, run: AgentRun, user_id_entity: EntityId | None) -> dict:
        """Enter the reasoning loop, loading context only on a run's first turn.

        The resolved identity travels in the turn so every audit entry in the loop
        is attributable without re-deriving it, and so ``execute`` cannot reach a
        ``None`` user part-way through.
        """
        if run.status is AgentRunStatus.CREATED:
            self._transition(run, AgentRunStatus.CONTEXT_LOADING)
            available = self.available_tools(run.user_request)
            context = self.context_builder.build(
                run, available, user_id=user_id_entity
            )
            self._transition(run, AgentRunStatus.PLANNING)
            return {
                "context": context,
                "available": available,
                "counters": self._reset_budget(run),
                "user_id": user_id_entity,
            }

        # Re-entering a run that is already under way. Restarting the context
        # phase would be an illegal transition and would throw away what the run
        # has already established, so the existing budget carries over instead.
        self._transition(run, AgentRunStatus.PLANNING)
        available = self.available_tools(run.user_request)
        return {
            "context": self.context_builder.build(
                run, available, user_id=user_id_entity
            ),
            "available": available,
            "counters": self._budget(run),
            "user_id": user_id_entity,
        }

    def available_tools(self, request: str) -> list[ToolDefinition]:
        if self.tool_catalog is not None:
            return self.tool_catalog.available_definitions(request)
        return self.tool_registry.definitions()

    def _tool_context(
        self,
        run: AgentRun,
        skill_names: frozenset[str],
        user_id: EntityId | None = None,
        authorization: ExecutionAuthorization | None = None,
    ) -> ToolContext:
        return ToolContext(
            agent_id=run.agent_id,
            agent_run_id=run.id,
            # The acting user is propagated into the execution context. It used
            # to be dropped here, which left ``ToolContext.user_id`` permanently
            # None and therefore every ``RuntimeSession.user_id`` null -- so the
            # runtime's ownership check compared None to None and could never
            # fail. Identity now survives all the way to the sandbox record.
            user_id=user_id,
            user_request=run.user_request,
            correlation_id=str(run.id),
            skill_names=skill_names,
            authorization=authorization,
        )

    # -- the single authorization path ------------------------------------

    def _gate(
        self,
        run: AgentRun,
        tool,
        arguments: dict,
        user_id_entity: EntityId | None,
        available_names: frozenset[str],
        *,
        human_approved: bool = False,
    ) -> _GateOutcome:
        """Plan validation, then Trust Engine, then mint proof. In that order.

        Both ``execute`` and ``resume`` go through here. That is the structural
        fix for the bypass this class used to contain: resume had its own copy of
        the authorization logic, it omitted the Trust Engine entirely, and the two
        copies drifted. One implementation cannot drift.

        ``human_approved`` records that a person said yes. It is *not* authority:
        the Trust Engine still decides, and an ASK is still escalated. A human who
        approves an action the current policy forbids gets an audit event and a
        refusal, because an approval issued minutes ago under a policy that has
        since changed is not a permanent authorisation.
        """
        tool_name = tool.definition().name

        # -- 1. plan validation ------------------------------------------------
        if self.plan_validator is not None:
            result: PlanValidationResult = self.plan_validator.validate(
                ProposedPlan(
                    agent_id=run.agent_id,
                    agent_run_id=run.id,
                    actions=(ProposedAction(tool_name=tool_name, arguments=arguments),),
                    available_tool_names=available_names,
                )
            )
            if not result.valid:
                # A non-blocking violation is a warning, not a refusal: the
                # validator can only narrow, so anything it does not block is the
                # Trust Engine's business.
                blocking = result.blocking_violations
                if not blocking:
                    blocking = result.violations
                reason = (
                    "; ".join(violation.reason for violation in blocking)
                    or "plan rejected by the plan validator"
                )
                self._audit(
                    AuthorizationEventType.PLAN_REJECTED,
                    user_id=user_id_entity,
                    run=run,
                    tool_name=tool_name,
                    reason=reason,
                )
                action = self._record_action(
                    run,
                    tool,
                    arguments,
                    risk_level=tool.definition().risk_level,
                    decision=PermissionDecision.DENY,
                    policy_id="plan_validator",
                )
                action.error_message = reason
                return _GateOutcome(
                    action=action,
                    decision=PermissionDecision.DENY,
                    reason=reason,
                    policy_id="plan_validator",
                    requires_confirmation=False,
                )

        # -- 2. trust engine --------------------------------------------------
        evaluation = self.trust_engine.evaluate(
            tool.definition(),
            user_id_entity,
            run.agent_id,
            run.id,
            arguments,
        )

        action = self._record_action(
            run,
            tool,
            arguments,
            risk_level=evaluation.risk_level,
            decision=evaluation.decision,
            policy_id=evaluation.policy_id,
        )

        if evaluation.decision is PermissionDecision.ALLOW and human_approved:
            # Recorded, because "a human approved it and the policy allowed it"
            # is a different provenance from "the policy allowed it", and the two
            # must be distinguishable when auditing what ran.
            self._audit(
                AuthorizationEventType.TOOL_ALLOWED,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=evaluation.decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=evaluation.reason,
                extra={"human_approved": True},
            )
        elif evaluation.decision is PermissionDecision.ALLOW:
            self._audit(
                AuthorizationEventType.TOOL_ALLOWED,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=evaluation.decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=evaluation.reason,
            )
        elif evaluation.decision is PermissionDecision.ASK:
            self._audit(
                AuthorizationEventType.TOOL_DENIED,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=evaluation.decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=f"escalated for approval: {evaluation.reason}",
            )
        else:
            event = (
                AuthorizationEventType.PERMISSION_DENIED
                if evaluation.policy_id == "permission"
                else AuthorizationEventType.TOOL_DENIED
            )
            self._audit(
                event,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=evaluation.decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=evaluation.reason,
            )

        # -- 3. proof, only for an ALLOW -------------------------------------
        authorization = None
        if evaluation.decision is PermissionDecision.ALLOW:
            authorization = ExecutionAuthorization.allow(
                agent_id=run.agent_id,
                agent_run_id=run.id,
                tool_name=tool_name,
                user_id=user_id_entity,
                policy_id=evaluation.policy_id,
            )

        return _GateOutcome(
            action=action,
            decision=evaluation.decision,
            reason=evaluation.reason,
            policy_id=evaluation.policy_id,
            requires_confirmation=evaluation.requires_confirmation,
            authorization=authorization,
        )

    def _record_action(
        self,
        run: AgentRun,
        tool,
        arguments: dict,
        *,
        risk_level,
        decision: PermissionDecision,
        policy_id: str,
    ) -> AgentAction:
        action = AgentAction(
            run.id,
            tool.definition().skill_name,
            tool.definition().name,
            arguments,
            risk_level=risk_level,
            permission_decision=decision,
            policy_result=policy_id,
        )
        self.agent_action_repository.save(action)
        return action

    def _audit(
        self,
        event: AuthorizationEventType,
        *,
        user_id: EntityId | None = None,
        run: AgentRun | None = None,
        tool_name: str | None = None,
        reason: str | None = None,
        **fields,
    ) -> None:
        """Record a decision. Never raises: losing an audit line must not fail a run."""
        if self.security_audit is None:
            return
        try:
            self.security_audit.record(
                event,
                user_id=user_id,
                agent_id=run.agent_id if run is not None else None,
                agent_run_id=run.id if run is not None else None,
                tool_name=tool_name,
                reason=reason,
                **fields,
            )
        except Exception:  # noqa: BLE001 - auditing is best-effort by design
            logger.exception("failed to write a security audit entry")

    async def execute(self, run: AgentRun, user_id: str | None = None) -> AgentExecutionResult:
        user_id_entity = EntityId.from_string(user_id) if user_id else None
        turn = self._begin_turn(run, user_id_entity)
        context = turn["context"]
        available = turn["available"]
        observations = []
        try:
            available_names = frozenset(definition.name for definition in available)
            for _ in range(self.max_iterations):
                counters = turn["counters"]
                decision = await self.agent_brain.decide(run, context, available)
                try:
                    decision_type = AgentDecisionType(decision.decision_type)
                except ValueError:
                    # An unrecognised decision is never coerced into a tool call.
                    # Falling through would let a malformed brain response start
                    # executing things.
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(
                        run,
                        response="Agent returned an unsupported decision",
                        observations=observations,
                    )
                if decision_type is AgentDecisionType.FINAL:
                    self._transition(run, AgentRunStatus.COMPLETED)
                    return AgentExecutionResult(run, decision.response, observations=observations)
                if decision_type is AgentDecisionType.ASK_USER:
                    self._transition(run, AgentRunStatus.WAITING_PERMISSION)
                    return AgentExecutionResult(run, question=decision.question, observations=observations)
                if decision_type is AgentDecisionType.ERROR:
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(run, response=decision.error, observations=observations)
                if self._runtime_exhausted(run):
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"runtime budget exceeded after {self.max_runtime_seconds}s",
                    )
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(
                        run, response="Agent run exceeded its time budget", observations=observations
                    )
                if counters["tool_calls"] >= self.max_tool_calls:
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"tool-call budget exhausted at {self.max_tool_calls}",
                    )
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(run, response="Agent tool-call limit reached", observations=observations)
                if counters["permission_requests"] >= self.max_permission_requests:
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"permission-request budget exhausted at {self.max_permission_requests}",
                    )
                    self._transition(run, AgentRunStatus.BLOCKED)
                    return AgentExecutionResult(run, response="Agent permission request limit reached", observations=observations)
                if counters["denied_actions"] >= self.max_denied_actions:
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"denied-action budget exhausted at {self.max_denied_actions}",
                    )
                    self._transition(run, AgentRunStatus.BLOCKED)
                    return AgentExecutionResult(run, response="Agent denied action limit reached", observations=observations)

                if (decision.tool_name or "") not in available_names:
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(run, response="Requested tool is not available", observations=observations)
                tool = self.tool_registry.get(decision.tool_name)
                if tool is None:
                    self._transition(run, AgentRunStatus.FAILED)
                    return AgentExecutionResult(run, response="Requested tool is not available", observations=observations)

                # The one authorization path. Plan validation and the Trust Engine
                # both run here, in that order, so neither this loop nor resume
                # can reach an executor without passing them.
                gate = self._gate(
                    run,
                    tool,
                    decision.arguments,
                    turn["user_id"],
                    available_names,
                )
                action = gate.action

                if gate.decision is PermissionDecision.DENY:
                    action.transition_to(AgentActionStatus.BLOCKED)
                    action.error_message = gate.reason
                    self.agent_action_repository.save(action)
                    counters["denied_actions"] += 1
                    self._transition(run, AgentRunStatus.BLOCKED)
                    return AgentExecutionResult(run, response="Action blocked by policy", observations=observations, reason=gate.reason)

                if gate.decision is PermissionDecision.ASK:
                    # Create permission request if approval service is available
                    if self.approval_service:
                        self.approval_service.create_request(
                            agent_run_id=run.id,
                            tool_name=tool.definition().name,
                            skill_name=tool.definition().skill_name,
                            reason=gate.reason,
                            risk_level=action.risk_level,
                            arguments_summary=decision.arguments,
                            user_id=user_id_entity,
                        )
                        counters["permission_requests"] += 1

                    self._transition(run, AgentRunStatus.WAITING_PERMISSION)
                    return AgentExecutionResult(
                        run,
                        question=f"Allow {tool.definition().name}?",
                        observations=observations,
                        reason=gate.reason,
                    )

                outcome = await self._dispatch(
                    run, tool, action, gate.authorization, turn["user_id"]
                )
                if isinstance(outcome, AgentExecutionResult):
                    # The action failed in a way that ends the run.
                    return outcome
                observations.append(outcome)
                context.setdefault("observations", []).append(outcome)
                counters["tool_calls"] += 1
                self._transition(run, AgentRunStatus.PLANNING)

            self._transition(run, AgentRunStatus.FAILED)
            return AgentExecutionResult(run, response="Agent iteration limit reached", observations=observations)
        finally:
            self.agent_run_repository.save(run)

    async def _dispatch(
        self,
        run: AgentRun,
        tool,
        action: AgentAction,
        authorization: ExecutionAuthorization | None,
        user_id_entity: EntityId | None,
    ):
        """Move an ALLOWed action to its outcome.

        Returns the observation on success, or an :class:`AgentExecutionResult`
        when the run has already been moved to a terminal state and the caller
        must return it. That union return is why the caller checks
        ``isinstance``: a runtime failure cannot be reported as an observation,
        because an observation implies the tool ran.

        Both entry points call this, so the "what actually happens on the way to
        an executor" logic exists once.
        """
        if authorization is None:
            # Unreachable while _gate only mints on ALLOW, but this is the last
            # point before a process could start, and the invariant is cheap.
            raise AuthorizationError(
                "refusing to dispatch an action without an execution authorization"
            )

        action.transition_to(AgentActionStatus.APPROVED)
        action.transition_to(AgentActionStatus.EXECUTING)
        self.agent_action_repository.save(action)
        self._transition(run, AgentRunStatus.EXECUTING)

        try:
            observation = await self.tool_executor.execute(
                tool.definition().name,
                action.arguments,
                self._tool_context(
                    run,
                    frozenset({tool.definition().skill_name}),
                    user_id=user_id_entity,
                    authorization=authorization,
                ),
            )
        except (RuntimeUnavailableError, RuntimePolicyRejectedError) as error:
            # The sandbox could not be created, started or given a policy. The run
            # and the action are already EXECUTING, so letting this propagate
            # strands the run in a state nothing would move it out of. It fails
            # here instead, and it fails -- it is never retried on the host.
            action.transition_to(AgentActionStatus.FAILED)
            action.execution_status = "FAILED"
            self.agent_action_repository.save(action)
            self._transition(run, AgentRunStatus.FAILED)
            return AgentExecutionResult(run, response=f"Runtime unavailable: {error}")

        self._transition(run, AgentRunStatus.OBSERVING)
        action.transition_to(
            AgentActionStatus.COMPLETED if observation.success else AgentActionStatus.FAILED
        )
        action.execution_status = "SUCCESS" if observation.success else "FAILED"
        self.agent_action_repository.save(action)
        return observation

    async def resume(
        self, run: AgentRun, allow: bool, user_id: str | None = None
    ) -> AgentExecutionResult:
        """Continue a run that stopped for human approval.

        This used to mint an authorization straight from the human's yes, with no
        plan validation, no Trust Engine, no identity and no time budget. All four
        are now enforced, because the human's answer answers "is this the action
        you meant?", not "is this action allowed under the policy in force now".
        """
        if run.status is not AgentRunStatus.WAITING_PERMISSION:
            raise ValueError("agent run is not waiting for permission")
        actions = self.agent_action_repository.list_by_run(run.id)
        if not actions:
            raise ValueError("pending action not found")
        action = actions[-1]
        tool = self.tool_registry.get(action.action_name)
        if tool is None:
            raise ValueError("pending tool not found")

        # Identity is resolved once and bound to the execution context. Passing
        # the caller down by string and coercing it inside the run is what let a
        # resume execute without the user_id that the original execute saw.
        user_id_entity = EntityId.from_string(user_id) if user_id else None
        if user_id_entity is None:
            self._audit(
                AuthorizationEventType.TRUST_ENGINE_BYPASS_ATTEMPT,
                run=run,
                tool_name=action.action_name,
                reason="resume attempted without an acting user",
            )
            raise AuthorizationError("resuming a run requires the acting user")

        counters = self._budget(run)
        if counters["tool_calls"] >= self.max_tool_calls:
            # Resuming repeatedly is a way to keep dispatching actions against a
            # budget that only execute() was meant to bound. The budget is the
            # run's, so it applies here too.
            self._audit(
                AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason=f"tool-call budget already exhausted at {self.max_tool_calls}",
            )
            self._transition(run, AgentRunStatus.BLOCKED)
            return AgentExecutionResult(run, response="Agent tool-call limit reached")

        if self._runtime_exhausted(run):
            self._audit(
                AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason=f"resume attempted after the {self.max_runtime_seconds}s run budget expired",
            )
            self._transition(run, AgentRunStatus.FAILED)
            return AgentExecutionResult(
                run, response="Agent run exceeded its time budget"
            )

        pending_request = (
            self.approval_service.get_pending_by_run(run.id)
            if self.approval_service
            else None
        )
        if pending_request is None:
            # There is nothing for the human to have been asked about. Executing
            # anyway would mean trusting a run's claim to be waiting on a decision
            # that no longer exists, so this refuses instead of inferring consent.
            self._audit(
                AuthorizationEventType.TRUST_ENGINE_BYPASS_ATTEMPT,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason="resume found no pending permission request to approve",
            )
            raise ValueError("pending permission request not found")

        if pending_request.tool_name != action.action_name:
            self._audit(
                AuthorizationEventType.TRUST_ENGINE_BYPASS_ATTEMPT,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason=f"pending request covers {pending_request.tool_name}",
            )
            raise ValueError("pending permission request does not match the pending action")
        if pending_request.is_expired():
            if self.approval_service is not None:
                self.approval_service.expire(pending_request.id)
            self._audit(
                AuthorizationEventType.PERMISSION_EXPIRED,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason="approval window closed before a decision was made",
            )
            action.transition_to(AgentActionStatus.BLOCKED)
            action.error_message = "Approval request expired"
            self.agent_action_repository.save(action)
            self._transition(run, AgentRunStatus.BLOCKED)
            return AgentExecutionResult(run, response="Approval request expired")

        if not allow:
            if self.approval_service is not None:
                self.approval_service.reject(pending_request.id)
            action.transition_to(AgentActionStatus.BLOCKED)
            action.error_message = "Action denied by user"
            self.agent_action_repository.save(action)
            self._transition(run, AgentRunStatus.BLOCKED)
            return AgentExecutionResult(run, response="Action denied by user")

        # Re-decide under current policy. The human approved this action; the
        # policy in force when they answered may not allow it, and the tool may
        # have been removed or disabled since. Both are re-checked here rather
        # than assumed from the stored action.
        available_names = frozenset(
            definition.name
            for definition in (tool.definition(),)  # the pending tool is the scope
        )
        gate = self._gate(
            run,
            tool,
            action.arguments,
            user_id_entity,
            available_names,
            human_approved=True,
        )

        if gate.decision is PermissionDecision.ALLOW:
            if self.approval_service is not None:
                self.approval_service.approve(pending_request.id)

        if gate.decision is PermissionDecision.DENY:
            if self.approval_service is not None:
                self.approval_service.reject(pending_request.id)
            self._audit(
                AuthorizationEventType.APPROVAL_OVERRULED,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                decision=gate.decision.value,
                policy_id=gate.policy_id,
                reason=gate.reason,
                extra={"human_approved": True},
            )
            action.transition_to(AgentActionStatus.BLOCKED)
            action.error_message = gate.reason
            self.agent_action_repository.save(action)
            counters["denied_actions"] += 1
            self._transition(run, AgentRunStatus.BLOCKED)
            return AgentExecutionResult(
                run,
                response="Action blocked by policy despite approval",
                reason=gate.reason,
            )

        if gate.decision is PermissionDecision.ASK:
            # Still asks under current policy. The approval stands recorded, but
            # it does not satisfy a second, stricter question.
            self._audit(
                AuthorizationEventType.APPROVAL_OVERRULED,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                decision=gate.decision.value,
                policy_id=gate.policy_id,
                reason=f"policy now requires approval again: {gate.reason}",
                extra={"human_approved": True},
            )
            self._transition(run, AgentRunStatus.WAITING_PERMISSION)
            return AgentExecutionResult(
                run,
                question=f"Allow {tool.definition().name}?",
                reason=gate.reason,
            )

        outcome = await self._dispatch(run, tool, action, gate.authorization, user_id_entity)
        counters["tool_calls"] += 1
        if isinstance(outcome, AgentExecutionResult):
            return outcome
        return AgentExecutionResult(
            run,
            response="Action completed" if outcome.success else "Action failed",
            observations=[outcome],
        )

    def _transition(self, run: AgentRun, status: AgentRunStatus) -> None:
        # Re-entering a run can legitimately ask for the state it is already in.
        # That is not a transition, so it is not validated as one.
        if run.status is not status:
            self.state_service.transition(run, status)
        self.agent_run_repository.save(run)
