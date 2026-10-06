"""``ToolExecutor`` that routes sandbox-backed tools through ``AgentRuntimePort``.

This is the seam that makes Phase 10 actually reachable from an agent run. Two
rules are enforced here and nowhere else:

1. A sandbox-backed tool will not run without an ``ExecutionAuthorization``. If
   the Trust Engine did not mint one, the call is refused rather than quietly
   falling through to the in-process executor.
2. When the sandbox cannot be created or started, the call fails. It is never
   retried on the host.

Tools that are not sandbox-backed are delegated unchanged to the in-process
executor, so the behaviour of Phases 1-9 is preserved exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.application.agent_runtime.policy_factory import RuntimePolicyFactory
from app.application.agent_runtime.service import AgentRuntimeService
from app.domain.ports.agent_runtime import ExecutionRequest
from app.domain.ports.tool import ToolContext, ToolDefinition, ToolObservation
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.value_objects.execution_authorization import ExecutionAuthorization

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SandboxCommand:
    """How one tool becomes a sandboxed command.

    ``arguments`` is a template rather than a free-form dict so the argv is
    built positionally. No argument can introduce a new token that the model did
    not already supply as a whole value, which is what keeps shell-style
    smuggling (``; rm -rf /``, ``$(...)``, backticks) out of reach: the command is
    always an argv list executed without a shell.
    """

    executable: str
    #: Positional argument template. Each ``{name}`` becomes one argv element.
    positionals: tuple[str, ...] = ()
    #: Fixed flags inserted before the positionals.
    flags: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    #: Argument names consumed by the template, so they can be removed.
    consumed: frozenset[str] = frozenset()
    needs_network: bool = False
    #: Destinations the command will contact, as ``(host, port)``.
    #:
    #: ``needs_network`` alone is only a hint used to pick a policy; this is the
    #: set that gets checked against ``RuntimePolicy.allows_endpoint`` before the
    #: process starts. A tool that declares egress it cannot justify is refused
    #: instead of being trusted because its binary is allowlisted.
    endpoints: tuple[tuple[str, int], ...] = ()

    def build(self, arguments: Mapping[str, Any]) -> tuple[str, ...]:
        values = dict(arguments)
        rendered: list[str] = []
        for item in self.positionals:
            if "{" not in item:
                rendered.append(item)
                continue
            name = item.strip("{}")
            if name not in values:
                raise ValueError(f"missing required argument {name!r}")
            rendered.append(_scalar(values.pop(name)))
        for item in self.flags:
            if "{" not in item:
                rendered.append(item)
                continue
            name = item.strip("{}")
            if name not in values:
                raise ValueError(f"missing required argument {name!r}")
            rendered.append(_scalar(values.pop(name)))
        if values:
            unexpected = ", ".join(sorted(values))
            raise ValueError(f"unexpected arguments for this tool: {unexpected}")
        return (self.executable, *rendered)


def _scalar(value: Any) -> str:
    """Render one argument as a single argv element."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise ValueError(f"argument of type {type(value).__name__} cannot be passed to a sandboxed command")


class RuntimeToolExecutor(ToolExecutor):
    """Dispatches tool calls to the sandbox, or to the plain executor."""

    def __init__(
        self,
        *,
        runtime_service: AgentRuntimeService,
        policy_factory: RuntimePolicyFactory,
        delegate: ToolExecutor,
        sandboxed_tools: Mapping[str, SandboxCommand],
        definitions: Mapping[str, ToolDefinition] | None = None,
    ) -> None:
        self.runtime_service = runtime_service
        self.policy_factory = policy_factory
        self.delegate = delegate
        self.sandboxed_tools = dict(sandboxed_tools)
        self.definitions = dict(definitions or {})

    async def execute(
        self, tool_name: str, arguments: dict, context: ToolContext
    ) -> ToolObservation:
        command = self.sandboxed_tools.get(tool_name)
        if command is None:
            return await self.delegate.execute(tool_name, arguments, context)

        if context.authorization is None:
            # Reaching here means something upstream bypassed the Trust Engine.
            # Refusing is the entire point of the authorization requirement.
            logger.warning(
                "refusing sandboxed tool %s for run %s: no authorization present",
                tool_name,
                context.agent_run_id,
            )
            return ToolObservation(
                tool_name=tool_name,
                success=False,
                error="AUTHORIZATION_DENIED: sandboxed execution requires a Trust Engine ALLOW",
                metadata={"runtime": True, "executed": False},
            )

        try:
            argv = command.build(arguments)
        except ValueError as error:
            return ToolObservation(
                tool_name=tool_name,
                success=False,
                error=f"INVALID_ARGUMENTS: {error}",
                metadata={"runtime": True, "executed": False},
            )

        policy = self.policy_factory.for_tool(
            self.definitions.get(tool_name),
            needs_network=command.needs_network,
            timeout_seconds=command.timeout_seconds,
        )
        session = await self.runtime_service.start_session(
            agent_id=context.agent_id,
            agent_run_id=context.agent_run_id,
            user_id=context.user_id,
            policy=policy,
        )
        try:
            outcome = await self.runtime_service.execute(
                session,
                ExecutionRequest(
                    agent_run_id=context.agent_run_id,
                    tool_name=tool_name,
                    command=argv,
                    working_directory=session.workspace_path,
                    timeout_seconds=command.timeout_seconds,
                    network_endpoints=command.endpoints,
                ),
                context.authorization,
                user_id=context.user_id,
            )
        finally:
            # The sandbox is torn down whatever happened, including on refusal.
            await self.runtime_service.stop_session(session, user_id=context.user_id)

        return ToolObservation(
            tool_name=tool_name,
            success=outcome.succeeded,
            output=outcome.output,
            error=outcome.error,
            metadata={
                "runtime": True,
                "provider": str(session.provider),
                "runtime_session_id": str(session.id),
                "sandbox_id": outcome.sandbox_id,
                "exit_code": outcome.exit_code,
                "truncated": outcome.truncated,
            },
        )


def sandboxed_tool_names(commands: Mapping[str, SandboxCommand]) -> Sequence[str]:
    return sorted(commands)


__all__ = ["RuntimeToolExecutor", "SandboxCommand", "sandboxed_tool_names"]