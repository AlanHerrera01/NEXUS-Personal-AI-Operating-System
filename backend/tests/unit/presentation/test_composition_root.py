"""The composition root is where isolation is actually enabled or lost.

Phase 10 shipped a correct sandboxing executor and a builder for it, and the
orchestrator was wired straight to the in-process registry executor instead. Every
security unit test passed while no sandbox was ever created in production. These
tests assert the wiring itself, because that is the part no other test can see.
"""

from __future__ import annotations

import pytest

from app.application.agent_runtime.runtime_tool_executor import RuntimeToolExecutor
from app.application.tools.executor import RegistryToolExecutor
from app.application.tools.registry import InMemoryToolRegistry
from app.config.settings import Settings
from app.infrastructure.skills.tasks.tools.create_task import TaskCreateTool
from app.presentation.dependencies.agent import build_skill_system, orchestrator_dependency
from app.presentation.dependencies.runtime import (
    SANDBOXED_TOOLS,
    build_runtime_tool_executor,
)


class _UnusedSession:
    """Stands in for the request-scoped SQLAlchemy session.

    ``build_skill_system`` only closes over the session inside repositories that
    none of these assertions touch.
    """


def enabled_settings(**overrides) -> Settings:
    base = {"runtime_enabled": True, "runtime_provider": "IN_MEMORY"}
    return Settings(**{**base, **overrides})


def orchestrator():
    return orchestrator_dependency(
        system=build_skill_system(_UnusedSession()),  # type: ignore[arg-type]
        session=_UnusedSession(),  # type: ignore[arg-type]
        trust_engine=object(),  # type: ignore[arg-type]
        approval_service=object(),  # type: ignore[arg-type]
    )


class TestRuntimeToolExecutorWiring:
    def test_the_orchestrator_executor_is_the_sandboxing_one(self) -> None:
        assert isinstance(orchestrator().tool_executor, RuntimeToolExecutor)

    def test_the_in_process_executor_stays_underneath_as_delegate(self) -> None:
        # Non-sandboxed tools must keep behaving exactly as in Phases 1-9, which
        # only holds if the registry executor is still reachable.
        assert isinstance(orchestrator().tool_executor.delegate, RegistryToolExecutor)

    def test_sandboxed_tools_follow_the_runtime_enabled_flag(self) -> None:
        # The default configuration has the runtime switched off, so the wired
        # executor carries no sandboxed tools. What must hold in both states is
        # that it is the sandboxing executor, so enabling the runtime cannot
        # require a code change to take effect.
        assert set(orchestrator().tool_executor.sandboxed_tools) == set()

    def test_enabling_the_runtime_populates_the_sandboxed_tools(self, monkeypatch) -> None:
        from app.presentation.dependencies import runtime as runtime_module

        monkeypatch.setattr(
            runtime_module, "get_settings", lambda: enabled_settings()
        )

        assert set(orchestrator().tool_executor.sandboxed_tools) == set(SANDBOXED_TOOLS)

    def test_tool_definitions_reach_the_executor(self) -> None:
        # The policy factory derives the filesystem and network posture from the
        # declared definition, so an empty mapping silently downgrades every
        # sandboxed tool to the bare baseline policy.
        assert orchestrator().tool_executor.definitions


class TestRuntimeEnabledSwitch:
    def test_disabled_runtime_leaves_no_sandboxed_tools(self) -> None:
        executor = build_runtime_tool_executor(
            delegate=RegistryToolExecutor(InMemoryToolRegistry()),
            settings=Settings(runtime_enabled=False),
        )

        assert isinstance(executor, RuntimeToolExecutor)
        assert executor.sandboxed_tools == {}

    def test_enabled_runtime_exposes_the_sandboxed_tools(self) -> None:
        executor = build_runtime_tool_executor(
            delegate=RegistryToolExecutor(InMemoryToolRegistry()),
            settings=enabled_settings(),
        )

        assert executor.sandboxed_tools

    @pytest.mark.parametrize("provider", ["OPENSHELL", "LOCAL", "IN_MEMORY"])
    def test_every_configured_provider_yields_a_runtime(self, provider: str) -> None:
        executor = build_runtime_tool_executor(
            delegate=RegistryToolExecutor(InMemoryToolRegistry()),
            settings=enabled_settings(runtime_provider=provider),
        )

        assert executor.runtime_service.provider is not None

    def test_an_unknown_provider_is_refused_rather_than_defaulted(self) -> None:
        # Falling back to a host runtime here would silently void every other
        # guarantee in this layer.
        with pytest.raises(RuntimeError):
            build_runtime_tool_executor(
                delegate=RegistryToolExecutor(InMemoryToolRegistry()),
                settings=enabled_settings(runtime_provider="HOST"),
            )


class TestSandboxedCommandShape:
    def test_no_sandboxed_tool_runs_through_a_shell(self) -> None:
        for command in SANDBOXED_TOOLS.values():
            assert command.executable.startswith("/")
            assert "sh" not in command.executable

    def test_every_sandboxed_binary_is_in_the_default_allowlist(self) -> None:
        allowlist = Settings().runtime_allowed_binaries.split(",")

        for command in SANDBOXED_TOOLS.values():
            assert command.executable in allowlist

    def test_a_sandboxed_tool_declares_no_unbounded_egress(self) -> None:
        for command in SANDBOXED_TOOLS.values():
            if command.needs_network:
                assert command.endpoints
            else:
                assert command.endpoints == ()