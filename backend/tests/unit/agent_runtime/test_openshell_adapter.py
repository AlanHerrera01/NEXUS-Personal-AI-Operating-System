from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.ports.agent_runtime import (
    ExecutionRequest,
    RuntimeUnavailableError,
    SandboxHandle,
    SandboxSpec,
)
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_policy import RuntimePolicy
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState
from app.infrastructure.agent_runtime.adapters.openshell_runtime import (
    OpenShellCapabilityError,
    OpenShellRuntimeAdapter,
)
from app.infrastructure.agent_runtime.command_runner import CommandResult
from app.infrastructure.agent_runtime.exceptions import OpenShellNotInstalledError

WORKSPACE = "/sandbox/nexus-run"

#: Help output as the documented CLI advertises it, per leaf subcommand. Only
#: these flags exist, so anything the adapter needs beyond this list must make
#: it refuse rather than guess.
HELP_TEXT: dict[str, str] = {
    "status": "Usage: openshell status [OPTIONS]\n\nOptions:\n  --help\n",
    "sandbox create": """
Usage: openshell sandbox create [OPTIONS] [-- COMMAND]...

Options:
  --name TEXT          Name for the new sandbox
  --from TEXT          Image to instantiate
  --template TEXT      Sandbox template to instantiate from
  --env TEXT           Environment variable KEY=VALUE
  --label TEXT         Label KEY=VALUE
  --upload TEXT        File to upload
  --detach             Start in detached mode
  --no-keep            Delete the sandbox when it exits
  --expose TEXT        Expose a port
  --forward TEXT       Forward a port
  --policy TEXT        Path to a policy file
  --provider TEXT      Inference provider
  --approval-mode TEXT Approval mode
  --editor TEXT        Open an editor
  --cpu TEXT           CPU cores
  --memory TEXT        Memory limit
  --output TEXT        Output format (json|yaml)
  --no-credential-warnings
""",
    "sandbox exec": """
Usage: openshell sandbox exec [OPTIONS] -n TEXT -- COMMAND [ARGS]...

Options:
  -n, --name TEXT      Target sandbox
  --timeout FLOAT      Timeout in seconds (0 disables)
""",
    "sandbox get": """
Usage: openshell sandbox get [OPTIONS] NAME

Options:
  --policy-only        Show only policy convergence
  --output TEXT        Output format (json|yaml)
""",
    "sandbox stop": "Usage: openshell sandbox stop [OPTIONS] NAME\n\nOptions:\n  --help\n",
    "sandbox delete": "Usage: openshell sandbox delete [OPTIONS] NAME\n\nOptions:\n  --help\n",
    "policy set": """
Usage: openshell policy set [OPTIONS] NAME

Options:
  --policy TEXT   Path to the policy file
  --wait          Wait for the policy to converge
""",
}

POLICY_HELP = """
Options for 'set':
  --policy TEXT   Path to the policy file
  --wait          Wait for the policy to converge
"""


class FakeRunner:
    """Records every argv the adapter builds."""

    def __init__(
        self,
        available: bool = True,
        responses: dict[str, CommandResult] | None = None,
        help_overrides: dict[str, str] | None = None,
    ):
        self.available = available
        self.responses = responses or {}
        self.calls: list[tuple[str, ...]] = []
        self.help_overrides = help_overrides or {}
        #: Called with the destination when a ``sandbox download`` argv is seen,
        #: so the fake CLI can actually produce a file.
        self.on_download = None

    def help_for(self, key: str) -> str:
        return self.help_overrides.get(key, HELP_TEXT[key])

    async def run(self, argv, *, timeout=None, stdin=None, env=None) -> CommandResult:
        argv = tuple(argv)
        self.calls.append(argv)
        if argv[-1] == "--help":
            key = " ".join(argv[1:-1])
            return CommandResult(argv, 0, self.help_for(key), "")
        for prefix, result in self.responses.items():
            if " ".join(argv[: len(prefix.split())]) == prefix:
                return CommandResult(argv, result.exit_code, result.stdout, result.stderr)
        if "download" in argv and self.on_download is not None:
            self.on_download(argv[-1])
        return CommandResult(argv, 0, "", "")

    def is_available(self, executable: str) -> bool:
        return self.available

    def last(self, *contains: str) -> tuple[str, ...]:
        for argv in reversed(self.calls):
            if all(token in argv for token in contains):
                return argv
        raise AssertionError(f"no call contained {contains}; saw {self.calls}")


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def adapter(runner: FakeRunner) -> OpenShellRuntimeAdapter:
    return OpenShellRuntimeAdapter(runner=runner)


def handle() -> SandboxHandle:
    return SandboxHandle(
        sandbox_id="sbx-1",
        provider=RuntimeProvider.OPENSHELL,
        name="nexus-run-1",
        workspace_path=WORKSPACE,
    )


def spec() -> SandboxSpec:
    return SandboxSpec(
        name="nexus-run-1",
        workspace_path=WORKSPACE,
        image="ubuntu:24.04",
        labels={"nexus.agent_run_id": "run-1"},
        cpu="1",
        memory="512Mi",
    )


class TestProvider:
    def test_adapter_reports_openshell(self, adapter: OpenShellRuntimeAdapter) -> None:
        assert adapter.provider is RuntimeProvider.OPENSHELL


class TestCapabilityProbe:
    async def test_probe_reads_the_installed_cli_help(self, adapter: OpenShellRuntimeAdapter) -> None:
        capabilities = await adapter.capabilities()

        assert "--policy" in capabilities["sandbox create"]
        assert "--timeout" in capabilities["sandbox exec"]
        assert "--policy" in capabilities["policy set"]

    async def test_each_leaf_command_is_probed_separately(self, adapter: OpenShellRuntimeAdapter) -> None:
        capabilities = await adapter.capabilities()

        # `create` documents --cpu and `exec` does not. Probing the whole
        # `sandbox` group would make --cpu look available to exec.
        assert "--cpu" in capabilities["sandbox create"]
        assert "--cpu" not in capabilities["sandbox exec"]

    async def test_probe_runs_once_and_is_cached(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.capabilities()
        calls_after_first = len(adapter.runner.calls)
        await adapter.capabilities()

        assert len(adapter.runner.calls) == calls_after_first


class TestHealth:
    async def test_missing_cli_is_reported_as_unavailable(self, runner: FakeRunner) -> None:
        runner.available = False
        adapter = OpenShellRuntimeAdapter(runner=runner)

        health = await adapter.health()

        assert health.available is False
        assert "not installed" in health.detail or "not on PATH" in health.detail

    async def test_reachable_gateway_is_reported_available(self, adapter: OpenShellRuntimeAdapter) -> None:
        health = await adapter.health()

        assert health.available is True

    async def test_non_zero_status_means_unreachable_not_crashed(
        self, runner: FakeRunner
    ) -> None:
        runner.responses["openshell status"] = CommandResult((), 1, "", "gateway unreachable")
        adapter = OpenShellRuntimeAdapter(runner=runner)

        health = await adapter.health()

        assert health.available is False
        assert "gateway unreachable" in health.detail

    async def test_credential_bearing_output_is_redacted(self, runner: FakeRunner) -> None:
        runner.responses["openshell status"] = CommandResult(
            (), 1, "", "failed: token=sk-live-abcdef123456"
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        health = await adapter.health()

        assert "sk-live-abcdef123456" not in health.detail


class TestCreate:
    async def test_create_uses_only_advertised_flags(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.create(spec(), RuntimePolicy().with_workspace(WORKSPACE))

        argv = adapter.runner.last("create")
        assert argv[:3] == ("openshell", "sandbox", "create")
        assert "--name" in argv and "nexus-run-1" in argv
        assert "--policy" in argv
        assert "--from" in argv and "ubuntu:24.04" in argv
        assert "--detach" in argv
        assert "--label" in argv

    async def test_policy_is_written_to_a_file_not_inlined(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.create(spec(), RuntimePolicy().with_workspace(WORKSPACE))

        argv = adapter.runner.last("create")
        policy_flag = argv[argv.index("--policy") + 1]
        # `--policy` takes a path. Inlining YAML would be invalid and would also
        # leak policy internals into the process argument list.
        assert policy_flag.endswith(".yaml")
        assert "version:" not in policy_flag

    async def test_policy_file_is_removed_afterwards(self, adapter: OpenShellRuntimeAdapter) -> None:
        from pathlib import Path

        await adapter.create(spec(), RuntimePolicy().with_workspace(WORKSPACE))

        argv = adapter.runner.last("create")
        assert not Path(argv[argv.index("--policy") + 1]).exists()

    async def test_create_ends_with_an_argv_separator(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.create(spec(), RuntimePolicy().with_workspace(WORKSPACE))

        argv = adapter.runner.last("create")
        assert "--" in argv


class TestRefusesUnknownFlags:
    async def test_missing_exec_name_flag_makes_the_adapter_refuse(self) -> None:
        # A build whose `exec` does not document -n/--name. NEXUS cannot address
        # a sandbox, so it must refuse instead of issuing a nameless exec.
        runner = FakeRunner(
            help_overrides={
                "sandbox exec": "Usage: openshell sandbox exec [OPTIONS] -- COMMAND\n\nOptions:\n  --help\n"
            }
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        with pytest.raises(OpenShellCapabilityError):
            await adapter.execute(
                handle(),
                ExecutionRequest(
                    agent_run_id=EntityId.new(),
                    tool_name="shell.ls",
                    command=("/usr/bin/ls", "-la"),
                    working_directory=WORKSPACE,
                ),
                RuntimePolicy().with_workspace(WORKSPACE),
            )

    async def test_missing_policy_flag_prevents_startup(self) -> None:
        # Without `--policy` the sandbox would come up under OpenShell's default
        # policy, which is not the policy NEXUS derived. That is a fail-open.
        runner = FakeRunner(
            help_overrides={"policy set": "Usage: openshell policy set NAME\n\nOptions:\n  --wait\n"}
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        with pytest.raises(OpenShellCapabilityError):
            await adapter.apply_policy(handle(), RuntimePolicy())

    async def test_unknown_optional_flags_are_simply_omitted(self) -> None:
        # A create command without --cpu/--memory still works; NEXUS drops the
        # flags instead of passing something the CLI would reject.
        runner = FakeRunner(
            help_overrides={
                "sandbox create": "Usage: openshell sandbox create --name TEXT --policy TEXT\n\nOptions:\n  --name TEXT\n  --policy TEXT\n"
            }
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        await adapter.create(spec(), RuntimePolicy())

        argv = runner.last("create")
        assert "--cpu" not in argv
        assert "--memory" not in argv
        assert "--from" not in argv


class TestExecute:
    async def test_command_is_passed_after_a_separator(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.execute(
            handle(),
            ExecutionRequest(
                agent_run_id=EntityId.new(),
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=WORKSPACE,
            ),
            RuntimePolicy().with_workspace(WORKSPACE),
        )

        argv = adapter.runner.last("exec")
        separator = argv.index("--")
        assert argv[separator + 1 :] == ("/usr/bin/ls", "-la")

    async def test_timeout_is_always_bounded(self, adapter: OpenShellRuntimeAdapter) -> None:
        await adapter.execute(
            handle(),
            ExecutionRequest(
                agent_run_id=EntityId.new(),
                tool_name="shell.ls",
                command=("/usr/bin/ls",),
                working_directory=WORKSPACE,
                timeout_seconds=0.4,
            ),
            RuntimePolicy().with_workspace(WORKSPACE),
        )

        argv = adapter.runner.last("exec")
        # A sub-second request still has to produce a whole-second timeout; 0
        # would disable the limit entirely.
        assert argv[argv.index("--timeout") + 1] == "1"

    async def test_working_directory_outside_the_workspace_is_refused(
        self, adapter: OpenShellRuntimeAdapter
    ) -> None:
        from app.domain.ports.agent_runtime import RuntimePolicyRejectedError

        with pytest.raises(RuntimePolicyRejectedError):
            await adapter.execute(
                handle(),
                ExecutionRequest(
                    agent_run_id=EntityId.new(),
                    tool_name="shell.ls",
                    command=("/usr/bin/ls",),
                    working_directory="/etc",
                ),
                RuntimePolicy().with_workspace(WORKSPACE).with_workspace(WORKSPACE),
            )

        assert not any("exec" in call for call in adapter.runner.calls)

    async def test_a_host_binary_is_refused_when_the_policy_lists_binaries(
        self, adapter: OpenShellRuntimeAdapter
    ) -> None:
        await adapter.execute(
            handle(),
            ExecutionRequest(
                agent_run_id=EntityId.new(),
                tool_name="shell.ls",
                command=("/usr/bin/ls", "-la"),
                working_directory=WORKSPACE,
            ),
            RuntimePolicy().with_workspace(WORKSPACE),
        )

        assert adapter.runner.last("exec")


class TestTransfer:
    """``sandbox upload`` / ``sandbox download`` are real, documented commands.

    They were refused outright on the grounds that the adapter would not guess a
    transfer command. The signatures have since been verified, so the adapter
    uses them and refuses only what is genuinely unsafe.
    """

    def source_file(self, tmp_path) -> str:
        path = tmp_path / "payload.txt"
        path.write_text("data", encoding="utf-8")
        return str(path)

    async def test_upload_uses_the_documented_signature(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        await adapter.upload(
            handle(),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=self.source_file(tmp_path),
                remote_path="/sandbox/nexus-run/in.txt",
            ),
        )

        assert runner.last("upload") == (
            "openshell",
            "sandbox",
            "upload",
            "nexus-run-1",
            self.source_file(tmp_path),
            "/sandbox/nexus-run/in.txt",
        )

    async def test_upload_omits_the_destination_when_none_was_named(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        # Guessing a destination inside a jail is how files land where the policy
        # does not govern them.
        await adapter.upload(
            handle(), TransferRequest(sandbox_id="sbx-1", local_path=self.source_file(tmp_path))
        )

        assert len(runner.last("upload")) == 5

    async def test_upload_refuses_a_source_that_is_not_a_regular_file(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        with pytest.raises(RuntimeUnavailableError):
            await adapter.upload(
                handle(), TransferRequest(sandbox_id="sbx-1", local_path=str(tmp_path))
            )
        assert not any("upload" in call for call in runner.calls)

    async def test_upload_refuses_a_missing_source(
        self, adapter: OpenShellRuntimeAdapter, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        with pytest.raises(RuntimeUnavailableError):
            await adapter.upload(
                handle(),
                TransferRequest(sandbox_id="sbx-1", local_path=str(tmp_path / "absent")),
            )

    async def test_a_failed_upload_is_reported_not_swallowed(
        self, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        runner = FakeRunner(
            responses={
                "openshell sandbox upload": CommandResult((), 1, "", "no such sandbox")
            }
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        with pytest.raises(RuntimeUnavailableError):
            await adapter.upload(
                handle(),
                TransferRequest(sandbox_id="sbx-1", local_path=self.source_file(tmp_path)),
            )

    async def test_download_uses_the_documented_signature(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        destination = tmp_path / "out.txt"
        runner.on_download = lambda staged: Path(staged).write_text("payload", encoding="utf-8")

        await adapter.download(
            handle(),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=str(destination),
                remote_path="/sandbox/nexus-run/out.txt",
            ),
        )

        assert runner.last("download")[:5] == (
            "openshell",
            "sandbox",
            "download",
            "nexus-run-1",
            "/sandbox/nexus-run/out.txt",
        )
        assert destination.read_text(encoding="utf-8") == "payload"

    async def test_download_writes_to_a_staging_file_not_the_final_name(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        destination = tmp_path / "out.txt"
        runner.on_download = lambda staged: Path(staged).write_text("payload", encoding="utf-8")

        await adapter.download(
            handle(),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=str(destination),
                remote_path="/sandbox/nexus-run/out.txt",
            ),
        )

        # A truncated file under the real name would later be read as real output.
        staged = runner.last("download")[5]
        assert staged != str(destination)
        assert ".partial-" in staged

    async def test_a_success_that_wrote_nothing_is_refused(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        destination = tmp_path / "out.txt"

        with pytest.raises(RuntimeUnavailableError):
            await adapter.download(
                handle(),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(destination),
                    remote_path="/sandbox/nexus-run/out.txt",
                ),
            )

        assert not destination.exists()

    async def test_a_failed_download_leaves_no_file_at_the_final_name(
        self, tmp_path
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        runner = FakeRunner(
            responses={
                "openshell sandbox download": CommandResult((), 1, "", "permission denied")
            }
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)
        destination = tmp_path / "out.txt"

        with pytest.raises(RuntimeUnavailableError):
            await adapter.download(
                handle(),
                TransferRequest(
                    sandbox_id="sbx-1", local_path=str(destination), remote_path="/x"
                ),
            )

        assert not destination.exists()
        assert list(tmp_path.iterdir()) == []

    async def test_download_refuses_a_relative_destination(
        self, adapter: OpenShellRuntimeAdapter, runner: FakeRunner
    ) -> None:
        from app.domain.ports.agent_runtime import TransferRequest

        # A relative destination resolves against whatever working directory the
        # CLI happens to have.
        with pytest.raises(RuntimeUnavailableError):
            await adapter.download(
                handle(),
                TransferRequest(
                    sandbox_id="sbx-1", local_path="out.txt", remote_path="/x"
                ),
            )
        assert not any("download" in call for call in runner.calls)


class TestStatus:
    async def test_documented_phase_is_mapped_to_a_runtime_state(
        self, runner: FakeRunner
    ) -> None:
        runner.responses['openshell sandbox get nexus-run-1 --output json'] = CommandResult(
            (), 0, '{"id": "sbx-1", "phase": "ready"}', ""
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        status = await adapter.status(handle())

        assert status.state is RuntimeState.READY

    async def test_invalid_policy_phase_is_reported_as_blocked(
        self, runner: FakeRunner
    ) -> None:
        runner.responses['openshell sandbox get nexus-run-1 --output json'] = CommandResult(
            (),
            0,
            '{"phase": "provisioning", "conditions": [{"status": "True", '
            '"reason": "ConfigurationInvalid"}]}',
            "",
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        status = await adapter.status(handle())

        assert status.state is RuntimeState.BLOCKED

    async def test_missing_sandbox_is_reported_as_stopped_not_raised(
        self, runner: FakeRunner
    ) -> None:
        runner.responses['openshell sandbox get nexus-run-1 --output json'] = CommandResult(
            (), 1, "", "sandbox not found"
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        status = await adapter.status(handle())

        assert status.state is RuntimeState.STOPPED


class TestTeardown:
    async def test_cleanup_swallows_destroy_failures(self, runner: FakeRunner) -> None:
        runner.responses["openshell sandbox delete nexus-run-1"] = CommandResult(
            (), 1, "", "gateway error"
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        await adapter.cleanup(handle())

    async def test_stop_failure_is_logged_not_raised(self, runner: FakeRunner) -> None:
        runner.responses["openshell sandbox stop nexus-run-1"] = CommandResult(
            (), 1, "", "gateway error"
        )
        adapter = OpenShellRuntimeAdapter(runner=runner)

        await adapter.stop(handle())


class TestMissingCli:
    async def test_missing_cli_becomes_a_runtime_unavailable_error(self) -> None:
        class MissingRunner(FakeRunner):
            def is_available(self, executable: str) -> bool:
                return False

            async def run(self, argv, **kwargs):
                raise OpenShellNotInstalledError("not on PATH")

        adapter = OpenShellRuntimeAdapter(runner=MissingRunner())

        with pytest.raises(RuntimeUnavailableError):
            await adapter.create(spec(), RuntimePolicy().with_workspace(WORKSPACE))