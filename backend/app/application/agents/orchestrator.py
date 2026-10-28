import json
import logging
import re
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
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition
from app.domain.ports.tool_catalog import ToolCatalog
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.ports.mcp_tool_provider import MCPToolProviderPort
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

#: How many earlier exchanges are replayed into the model context. A chat is a
#: conversation, not a pile of unrelated runs; the window is bounded so a long
#: thread cannot crowd out the current request.
MAX_CONVERSATION_TURNS = 8

#: Runs still in flight have no answer to replay yet and are skipped.
_IN_PROGRESS = frozenset(
    {
        AgentRunStatus.CREATED,
        AgentRunStatus.CONTEXT_LOADING,
        AgentRunStatus.PLANNING,
        AgentRunStatus.EXECUTING,
        AgentRunStatus.OBSERVING,
    }
)


def _history_answer(text: str | None) -> str:
    """Recover the prose from a legacy decision envelope, if one is present."""
    value = (text or "").strip()
    if not value.startswith("{"):
        return value
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and str(payload.get("decision", "")).upper() == "FINAL":
        response = payload.get("response")
        if isinstance(response, str):
            return response.strip()

    # Old runs can contain a FINAL envelope whose response has literal newlines,
    # which is invalid JSON. The field is still unambiguous; escape only those
    # control characters so the next model sees prose instead of the wrapper.
    match = re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', value, re.DOTALL)
    if match:
        raw = match.group(1).replace("\r\n", "\n").replace("\n", "\\n")
        try:
            decoded = json.loads(f'"{raw}"')
            if isinstance(decoded, str) and decoded.strip():
                return decoded.strip()
        except (TypeError, ValueError):
            pass
    return value


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
        mcp_tool_provider: MCPToolProviderPort | None = None,
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
        self.mcp_tool_provider = mcp_tool_provider
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

    def _conversation_history(
        self, run: AgentRun, user_id_entity: EntityId | None
    ) -> list[dict[str, str]]:
        """Earlier exchanges in the same conversation, oldest first.

        A run carries its conversation id, so the previous turns are already
        stored. Replaying them is what lets "y eso?" or "pero lo buscaste en la
        web" refer to the subject of the thread instead of arriving as a brand
        new request with no context. Owner-scoped like every other run read, and
        bounded so a long thread cannot crowd out the current request.
        """
        if run.conversation_id is None or user_id_entity is None:
            return []

        history: list[dict[str, str]] = []
        for previous in self.agent_run_repository.list_by_conversation(
            run.conversation_id, user_id_entity
        ):
            if previous.id == run.id or previous.status in _IN_PROGRESS:
                continue
            request = (previous.user_request or "").strip()
            answer = _history_answer(previous.response or previous.question)
            if not request and not answer:
                continue
            history.append({"request": request, "response": answer})
        return history[-MAX_CONVERSATION_TURNS:]

    def _build_context(
        self,
        run: AgentRun,
        available: list[ToolDefinition],
        user_id_entity: EntityId | None,
    ) -> dict:
        return self.context_builder.build(
            run,
            available,
            user_id=user_id_entity,
            conversation_history=self._conversation_history(run, user_id_entity),
        )

    def _begin_turn(
        self,
        run: AgentRun,
        user_id_entity: EntityId | None,
        extra_definitions: list[ToolDefinition] | None = None,
    ) -> dict:
        """Enter the reasoning loop, loading context only on a run's first turn.

        The resolved identity travels in the turn so every audit entry in the loop
        is attributable without re-deriving it, and so ``execute`` cannot reach a
        ``None`` user part-way through.
        """
        if run.status is AgentRunStatus.CREATED:
            self._transition(run, AgentRunStatus.CONTEXT_LOADING)
            available = self._merge_definitions(
                self.available_tools(run.user_request), extra_definitions
            )
            context = self._build_context(run, available, user_id_entity)
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
        available = self._merge_definitions(
            self.available_tools(run.user_request), extra_definitions
        )
        return {
            "context": self._build_context(run, available, user_id_entity),
            "available": available,
            "counters": self._budget(run),
            "user_id": user_id_entity,
        }

    def available_tools(self, request: str) -> list[ToolDefinition]:
        if self.tool_catalog is not None:
            return self.tool_catalog.available_definitions(request)
        return self.tool_registry.definitions()

    @staticmethod
    def _merge_definitions(
        base: list[ToolDefinition], extra: list[ToolDefinition] | None
    ) -> list[ToolDefinition]:
        if not extra:
            return base
        known = {definition.name for definition in base}
        return [*base, *(definition for definition in extra if definition.name not in known)]

    async def _load_mcp_tools(self, user_id_entity: EntityId | None) -> list[Tool]:
        """Discover MCP tools for this run and register them temporarily.

        Discovery failures are deliberately non-fatal. An unreachable MCP
        server should remove its own tools from the run, not turn every chat
        request into a 500. The panel reports the reason separately.
        """
        if self.mcp_tool_provider is None or user_id_entity is None:
            return []
        try:
            discovered = await self.mcp_tool_provider.tools_for_owner(user_id_entity)
        except Exception:  # noqa: BLE001 - discovery is an enhancement, not the run
            logger.exception("MCP tool discovery failed; continuing without MCP tools")
            return []

        registered: list[Tool] = []
        for tool in discovered:
            try:
                self.tool_registry.register(tool)
            except ValueError:
                logger.warning(
                    "MCP tool %s collides with an existing tool; skipped",
                    tool.definition().name,
                )
                continue
            registered.append(tool)
        return registered

    def _release_mcp_tools(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.tool_registry.unregister(tool.definition().name)

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
        existing_action: AgentAction | None = None,
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

        ``existing_action`` is set by ``resume`` for the action it already has on
        record. The decision is written onto that action instead of a fresh one,
        so a resumed run does not accumulate a second copy of the step it was
        asked about.
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
                    existing=existing_action,
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

        # An ASK means "a person must confirm this before it runs". A resume is
        # only ever reached because that person just answered the question, so
        # the confirmation is satisfied and the action proceeds. This is the one
        # and only thing that turns an ASK into an execution: a DENY is never
        # converted, and every check above (plan validation, the policy engine)
        # still ran. Without it the confirmation requirement could never be
        # satisfied -- a tool that asks (requires_confirmation, or a medium-risk
        # policy) would re-ask on every resume instead of ever executing.
        decision = evaluation.decision
        reason = evaluation.reason
        if decision is PermissionDecision.ASK and human_approved:
            decision = PermissionDecision.ALLOW
            reason = f"approved by the user; {evaluation.reason}"

        action = self._record_action(
            run,
            tool,
            arguments,
            risk_level=evaluation.risk_level,
            decision=decision,
            policy_id=evaluation.policy_id,
            existing=existing_action,
        )

        if decision is PermissionDecision.ALLOW:
            # Recorded, because "a human approved it and the policy allowed it"
            # is a different provenance from "the policy allowed it", and the two
            # must be distinguishable when auditing what ran.
            self._audit(
                AuthorizationEventType.TOOL_ALLOWED,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=reason,
                extra={"human_approved": True} if human_approved else None,
            )
        elif decision is PermissionDecision.ASK:
            self._audit(
                AuthorizationEventType.TOOL_DENIED,
                user_id=user_id_entity,
                run=run,
                tool_name=tool_name,
                decision=decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=f"escalated for approval: {reason}",
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
                decision=decision.value,
                risk_level=evaluation.risk_level.value,
                policy_id=evaluation.policy_id,
                reason=reason,
            )

        # -- 3. proof, only for an ALLOW -------------------------------------
        authorization = None
        if decision is PermissionDecision.ALLOW:
            authorization = ExecutionAuthorization.allow(
                agent_id=run.agent_id,
                agent_run_id=run.id,
                tool_name=tool_name,
                user_id=user_id_entity,
                policy_id=evaluation.policy_id,
            )

        return _GateOutcome(
            action=action,
            decision=decision,
            reason=reason,
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
        existing: AgentAction | None = None,
    ) -> AgentAction:
        if existing is None:
            action = AgentAction(
                run.id,
                tool.definition().skill_name,
                tool.definition().name,
                arguments,
                risk_level=risk_level,
                permission_decision=decision,
                policy_result=policy_id,
            )
        else:
            # Resuming re-decides the action that was proposed, rather than
            # recording a second copy of it: the step the operator approved and
            # the step that ran must be one row, or a reopened run reads back
            # with its plan step duplicated. The earlier ASK is not lost -- it is
            # in the audit trail and in the permission request that was raised.
            action = existing
            action.risk_level = risk_level
            action.permission_decision = decision
            action.policy_result = policy_id
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
        mcp_tools = await self._load_mcp_tools(user_id_entity)
        try:
            turn = self._begin_turn(
                run,
                user_id_entity,
                extra_definitions=[tool.definition() for tool in mcp_tools],
            )
        except BaseException:
            self._release_mcp_tools(mcp_tools)
            raise
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
                    self._transition(
                        run,
                        AgentRunStatus.FAILED,
                        response="Agent returned an unsupported decision",
                    )
                    return AgentExecutionResult(
                        run,
                        response="Agent returned an unsupported decision",
                        observations=observations,
                    )
                if decision_type is AgentDecisionType.FINAL:
                    self._transition(
                        run, AgentRunStatus.COMPLETED, response=decision.response
                    )
                    return AgentExecutionResult(run, decision.response, observations=observations)
                if decision_type is AgentDecisionType.ASK_USER:
                    self._transition(
                        run, AgentRunStatus.WAITING_PERMISSION, question=decision.question
                    )
                    return AgentExecutionResult(run, question=decision.question, observations=observations)
                if decision_type is AgentDecisionType.ERROR:
                    self._transition(
                        run, AgentRunStatus.FAILED, response=decision.error
                    )
                    return AgentExecutionResult(run, response=decision.error, observations=observations)
                if self._runtime_exhausted(run):
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"runtime budget exceeded after {self.max_runtime_seconds}s",
                    )
                    self._transition(
                        run,
                        AgentRunStatus.FAILED,
                        response="Agent run exceeded its time budget",
                    )
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
                    self._transition(
                        run,
                        AgentRunStatus.FAILED,
                        response="Agent tool-call limit reached",
                    )
                    return AgentExecutionResult(run, response="Agent tool-call limit reached", observations=observations)
                if counters["permission_requests"] >= self.max_permission_requests:
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"permission-request budget exhausted at {self.max_permission_requests}",
                    )
                    self._transition(
                        run,
                        AgentRunStatus.BLOCKED,
                        response="Agent permission request limit reached",
                    )
                    return AgentExecutionResult(run, response="Agent permission request limit reached", observations=observations)
                if counters["denied_actions"] >= self.max_denied_actions:
                    self._audit(
                        AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                        user_id=turn["user_id"],
                        run=run,
                        tool_name=decision.tool_name,
                        reason=f"denied-action budget exhausted at {self.max_denied_actions}",
                    )
                    self._transition(
                        run,
                        AgentRunStatus.BLOCKED,
                        response="Agent denied action limit reached",
                    )
                    return AgentExecutionResult(run, response="Agent denied action limit reached", observations=observations)

                if (decision.tool_name or "") not in available_names:
                    self._transition(
                        run,
                        AgentRunStatus.FAILED,
                        response="Requested tool is not available",
                    )
                    return AgentExecutionResult(run, response="Requested tool is not available", observations=observations)
                tool = self.tool_registry.get(decision.tool_name)
                if tool is None:
                    self._transition(
                        run,
                        AgentRunStatus.FAILED,
                        response="Requested tool is not available",
                    )
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
                    self._transition(
                        run, AgentRunStatus.BLOCKED, response="Action blocked by policy"
                    )
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

                    self._transition(
                        run,
                        AgentRunStatus.WAITING_PERMISSION,
                        question=f"Allow {tool.definition().name}?",
                    )
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

            self._transition(
                run,
                AgentRunStatus.FAILED,
                response="Agent iteration limit reached",
            )
            return AgentExecutionResult(run, response="Agent iteration limit reached", observations=observations)
        finally:
            self._release_mcp_tools(mcp_tools)
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
            self._transition(
                run, AgentRunStatus.FAILED, response=f"Runtime unavailable: {error}"
            )
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

        # A pending MCP tool lives in the request-scoped registry only for the
        # run that discovered it. Resume builds a new orchestrator, so the same
        # owner-scoped discovery has to happen before the pending tool can be
        # looked up again. Discovery failure surfaces as "pending tool not
        # found", which is the honest outcome: the action cannot run. A denial
        # never needs the tool, so it does not contact the server.
        mcp_tools: list[Tool] = []
        if allow and action.action_name.startswith("mcp."):
            mcp_tools = await self._load_mcp_tools(user_id_entity)
        try:
            return await self._resume_authorized(run, action, allow, user_id_entity)
        finally:
            self._release_mcp_tools(mcp_tools)

    async def _resume_authorized(
        self,
        run: AgentRun,
        action: AgentAction,
        allow: bool,
        user_id_entity: EntityId,
    ) -> AgentExecutionResult:
        tool = self.tool_registry.get(action.action_name)
        if tool is None:
            raise ValueError("pending tool not found")

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
            self._transition(
                run, AgentRunStatus.BLOCKED, response="Agent tool-call limit reached"
            )
            return AgentExecutionResult(run, response="Agent tool-call limit reached")

        if self._runtime_exhausted(run):
            self._audit(
                AuthorizationEventType.SUSPICIOUS_AGENT_LOOP,
                user_id=user_id_entity,
                run=run,
                tool_name=action.action_name,
                reason=f"resume attempted after the {self.max_runtime_seconds}s run budget expired",
            )
            self._transition(
                run,
                AgentRunStatus.FAILED,
                response="Agent run exceeded its time budget",
            )
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
            self._transition(
                run, AgentRunStatus.BLOCKED, response="Approval request expired"
            )
            return AgentExecutionResult(run, response="Approval request expired")

        if not allow:
            if self.approval_service is not None:
                self.approval_service.reject(pending_request.id)
            action.transition_to(AgentActionStatus.BLOCKED)
            action.error_message = "Action denied by user"
            self.agent_action_repository.save(action)
            self._transition(
                run, AgentRunStatus.BLOCKED, response="Action denied by user"
            )
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
            existing_action=action,
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
            self._transition(
                run,
                AgentRunStatus.BLOCKED,
                response="Action blocked by policy despite approval",
            )
            return AgentExecutionResult(
                run,
                response="Action blocked by policy despite approval",
                reason=gate.reason,
            )

        if gate.decision is PermissionDecision.ASK:
            # Defensive: resume always marks the decision human-approved, and a
            # human approval satisfies an ASK in _gate, so a resumed action does
            # not normally land here. Kept so that a caller who resumes without
            # that flag is asked again rather than silently executed.
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
            self._transition(
                run,
                AgentRunStatus.WAITING_PERMISSION,
                question=f"Allow {tool.definition().name}?",
            )
            return AgentExecutionResult(
                run,
                question=f"Allow {tool.definition().name}?",
                reason=gate.reason,
            )

        outcome = await self._dispatch(run, tool, action, gate.authorization, user_id_entity)
        counters["tool_calls"] += 1
        if isinstance(outcome, AgentExecutionResult):
            return outcome
        # The approved action ran and the resumed turn is over. Nothing else
        # continues a resumed run, and OBSERVING is not terminal, so without this
        # the run would sit in OBSERVING forever after its action completed.
        self._transition(
            run,
            AgentRunStatus.COMPLETED if outcome.success else AgentRunStatus.FAILED,
            response="Action completed" if outcome.success else "Action failed",
        )
        return AgentExecutionResult(
            run,
            response="Action completed" if outcome.success else "Action failed",
            observations=[outcome],
        )

    async def answer(
        self, run: AgentRun, answer: str, user_id: str | None = None
    ) -> AgentExecutionResult:
        """Continue a run that stopped to ask the user for missing detail.

        The counterpart to :meth:`resume`: that one answers an authorization,
        this one answers a question. A run waiting on a live permission request
        is refused here, so answering can never stand in for approving.
        """
        if run.status is not AgentRunStatus.WAITING_PERMISSION:
            raise ValueError("agent run is not waiting for an answer")
        if self.approval_service is not None and self.approval_service.get_pending_by_run(run.id):
            raise ValueError("agent run is waiting for a permission decision, not an answer")
        detail = (answer or "").strip()
        if not detail:
            raise ValueError("answer must not be empty")
        # The clarification is folded into the request the brain reads, because
        # that is what the prompt is built from; a side channel the planner never
        # sees would have it ask the same question again. Clearing the question
        # with it keeps the run from reporting a wait it is no longer in.
        run.user_request = f"{run.user_request}\n\nAclaración del usuario: {detail}"
        run.question = None
        self.agent_run_repository.save(run)
        return await self.execute(run, user_id=user_id)

    def _transition(
        self,
        run: AgentRun,
        status: AgentRunStatus,
        *,
        response: str | None = None,
        question: str | None = None,
    ) -> None:
        # Re-entering a run can legitimately ask for the state it is already in.
        # That is not a transition, so it is not validated as one.
        if run.status is not status:
            self.state_service.transition(run, status)
        # What the run has to say is written with the state it is said in and
        # saved by the same repository call, so a run read back later shows its
        # answer and not just its final status. Non-terminal transitions pass
        # neither, which is correct: a run that is still moving has no outcome.
        run.response = response
        run.question = question
        self.agent_run_repository.save(run)
