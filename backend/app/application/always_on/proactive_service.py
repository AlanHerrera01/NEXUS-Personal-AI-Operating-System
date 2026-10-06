"""Lets the user find out what NEXUS wants to say before it says it.

Two things are deliberately true here.

**No model is involved.** Every condition is arithmetic over the clock and counts
the caller already has, so "should I interrupt this person" is decided by code
that can be read and tested, not by a model that can decide differently on
Tuesday. See
:class:`~app.domain.services.proactive_evaluation_service.ProactiveEvaluationService`.

**The default action is to suggest, not to act.** ``SUGGEST`` returns text for
the UI to render and changes nothing else. ``RUN_AGENT`` does start a run, but
that run is created with the existing :class:`CreateAgentRunUseCase` and executed
by the existing :class:`AgentOrchestrator`, so it enters the Trust Engine like
anything else and stops in ``WAITING_PERMISSION`` if the policy says so. A
proactive trigger buys no privilege; it only supplies a ``user_request`` the user
themselves wrote into the rule.

A proactive run deliberately does not create a
:class:`~app.domain.entities.job_execution.JobExecution`. There is no scheduled
job behind it -- ``JobExecution.scheduled_job_id`` is mandatory and inventing a
phantom parent job to satisfy that would corrupt the job history. The agent run
itself is the durable record, queryable through the existing agent-run routes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.application.agents.orchestrator import AgentExecutionResult, AgentOrchestrator
from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.domain.entities._common import utc_now
from app.domain.entities.proactive_rule import (
    ACTION_RUN_AGENT,
    ACTION_SUGGEST,
    ProactiveRule,
)
from app.domain.repositories.proactive_rule_repository import ProactiveRuleRepository
from app.domain.services.proactive_evaluation_service import (
    ProactiveContext,
    ProactiveEvaluation,
    ProactiveEvaluationService,
)
from app.domain.value_objects.entity_id import EntityId


@dataclass(frozen=True)
class Suggestion:
    """A proactive nudge the user has not acted on."""

    rule_id: EntityId
    rule_name: str
    message: str
    reason: str


@dataclass
class ProactiveReport:
    now: datetime
    evaluated: int = 0
    suggestions: list[Suggestion] = field(default_factory=list)
    results: list[AgentExecutionResult] = field(default_factory=list)
    fired: list[EntityId] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ProactiveAgentService:
    """Evaluates a user's proactive rules and acts on the ones that match."""

    def __init__(
        self,
        *,
        proactive_rule_repository: ProactiveRuleRepository,
        evaluation_service: ProactiveEvaluationService,
        create_agent_run: CreateAgentRunUseCase,
        orchestrator: AgentOrchestrator,
        max_rules_per_pass: int = 50,
        logger: logging.Logger | None = None,
    ) -> None:
        self.proactive_rule_repository = proactive_rule_repository
        self.evaluation_service = evaluation_service
        self.create_agent_run = create_agent_run
        self.orchestrator = orchestrator
        self.max_rules_per_pass = max_rules_per_pass
        self.logger = logger or logging.getLogger(__name__)

    async def evaluate(
        self, user_id: EntityId, context: ProactiveContext, now: datetime | None = None
    ) -> ProactiveReport:
        """Evaluate every enabled rule for one user."""
        moment = now or context.now
        report = ProactiveReport(now=moment)

        rules = self.proactive_rule_repository.list_by_user(
            user_id, enabled_only=True, limit=self.max_rules_per_pass
        )
        report.evaluated = len(rules)

        for rule in rules:
            try:
                evaluation = self.evaluation_service.evaluate(rule, context)
            except Exception as error:  # noqa: BLE001
                report.errors.append(f"rule {rule.id}: {error}")
                continue

            if not evaluation.matched:
                continue

            # record_trigger applies the cooldown. Doing it here, before the
            # action, means a rule cannot fire twice even if the action itself
            # raises below.
            rule.record_trigger(moment)
            self.proactive_rule_repository.save(rule)
            report.fired.append(rule.id)

            if rule.action_type == ACTION_SUGGEST:
                report.suggestions.append(
                    Suggestion(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        message=rule.message,
                        reason=evaluation.reason,
                    )
                )
            elif rule.action_type == ACTION_RUN_AGENT:
                await self._run_agent(rule, report, moment)

        return report

    async def _run_agent(
        self, rule: ProactiveRule, report: ProactiveReport, now: datetime
    ) -> None:
        try:
            run = self.create_agent_run.execute(rule.agent_id, rule.message, rule.user_id)
        except ValueError as error:
            report.errors.append(f"rule {rule.id}: cannot start a run: {error}")
            return

        try:
            result = await self.orchestrator.execute(run, user_id=str(rule.user_id))
        except Exception as error:  # noqa: BLE001
            report.errors.append(f"rule {rule.id}: run raised: {error}")
            return

        report.results.append(result)

    def suggestions_for(
        self, user_id: EntityId, context: ProactiveContext, now: datetime | None = None
    ) -> list[Suggestion]:
        """Evaluate without running anything, for a read-only endpoint."""
        moment = now or context.now
        rules = self.proactive_rule_repository.list_by_user(
            user_id, enabled_only=True, limit=self.max_rules_per_pass
        )
        found: list[Suggestion] = []
        for rule in rules:
            try:
                evaluation = self.evaluation_service.evaluate(rule, context)
            except Exception:  # noqa: BLE001
                continue
            if evaluation.matched:
                found.append(
                    Suggestion(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        message=rule.message,
                        reason=evaluation.reason,
                    )
                )
        return found


__all__ = [
    "ProactiveAgentService",
    "ProactiveReport",
    "Suggestion",
    "ProactiveContext",
    "ProactiveEvaluation",
]