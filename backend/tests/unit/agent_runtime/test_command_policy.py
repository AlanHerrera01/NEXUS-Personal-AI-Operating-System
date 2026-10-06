from __future__ import annotations

import pytest

from app.application.agent_runtime.settings import DEFAULT_ALLOWED_COMMANDS, RuntimeLimitsConfig
from app.domain.value_objects.command_policy import CommandPolicy, FORBIDDEN_COMMANDS

WORKSPACE = "/srv/nexus/runs/abc"


@pytest.fixture
def policy() -> CommandPolicy:
    return RuntimeLimitsConfig().command_policy()


class TestForbiddenCommands:
    @pytest.mark.parametrize("executable", sorted(FORBIDDEN_COMMANDS))
    def test_dangerous_command_is_refused_even_if_configured(
        self, executable: str
    ) -> None:
        # A permissive allowlist must still not reach these. The forbidden set is
        # checked before the allowlist, so configuration cannot re-open them.
        wide_open = CommandPolicy.from_spec({executable: ()}, (executable,))

        assert wide_open.validate((executable,), WORKSPACE, WORKSPACE).allowed is False

    def test_absolute_path_to_a_forbidden_command_is_refused(self, policy: CommandPolicy) -> None:
        decision = policy.validate(("/bin/rm", "-rf", "/"), WORKSPACE, WORKSPACE)

        assert decision.allowed is False


class TestAllowlist:
    def test_unlisted_command_is_refused(self, policy: CommandPolicy) -> None:
        decision = policy.validate(("python", "-c", "print(1)"), WORKSPACE, WORKSPACE)

        assert decision.allowed is False
        assert "not in the allowlist" in decision.reason

    def test_empty_argv_is_refused(self, policy: CommandPolicy) -> None:
        assert policy.validate((), WORKSPACE, WORKSPACE).allowed is False

    def test_allowlisted_command_with_a_valid_flag_is_permitted(
        self, policy: CommandPolicy
    ) -> None:
        assert policy.validate(("ls", "-la"), WORKSPACE, WORKSPACE).allowed is True

    def test_file_name_arguments_are_allowed(self, policy: CommandPolicy) -> None:
        decision = policy.validate(("cat", "notes.txt"), WORKSPACE, WORKSPACE)

        assert decision.allowed is True

    def test_argument_count_is_bounded(self, policy: CommandPolicy) -> None:
        decision = policy.validate(
            ("cat", *[f"file-{index}.txt" for index in range(64)]), WORKSPACE, WORKSPACE
        )

        assert decision.allowed is False
        assert "too many arguments" in decision.reason


class TestEscapeAttempts:
    @pytest.mark.parametrize(
        "argument",
        [
            "../../etc/shadow",
            "../secret",
            "~/.ssh/id_rsa",
            "/root/.bashrc",
            "a;rm -rf /",
            "a&&b",
            "a||b",
            "a|b",
            "a>b",
            "$(whoami)",
            "${HOME}",
            "`id`",
            "a\nb",
        ],
    )
    def test_shell_and_traversal_sequences_are_refused(
        self, policy: CommandPolicy, argument: str
    ) -> None:
        decision = policy.validate(("cat", argument), WORKSPACE, WORKSPACE)

        assert decision.allowed is False

    def test_working_directory_outside_the_workspace_is_refused(
        self, policy: CommandPolicy
    ) -> None:
        decision = policy.validate(("ls", "-la"), "/etc", WORKSPACE)

        assert decision.allowed is False
        assert "outside the workspace" in decision.reason

    def test_absolute_path_outside_the_workspace_is_refused(
        self, policy: CommandPolicy
    ) -> None:
        decision = policy.validate(("cat", "/etc/shadow"), WORKSPACE, WORKSPACE)

        assert decision.allowed is False

    def test_workspace_sibling_with_a_shared_prefix_is_refused(
        self, policy: CommandPolicy
    ) -> None:
        decision = policy.validate(("cat", WORKSPACE + "-other/secret.txt"), WORKSPACE, WORKSPACE)

        assert decision.allowed is False

    def test_read_only_system_tree_stays_reachable(self, policy: CommandPolicy) -> None:
        # /usr is mounted read-only, so listing it is legitimate and should not
        # require a per-path exception in the policy.
        assert policy.validate(("cat", "/usr/share/doc/readme"), WORKSPACE, WORKSPACE).allowed is True

    def test_etc_is_not_treated_as_a_readable_system_tree(
        self, policy: CommandPolicy
    ) -> None:
        # /etc is excluded on purpose: it carries host configuration and can
        # include credential material.
        assert policy.validate(("cat", "/etc/hostname"), WORKSPACE, WORKSPACE).allowed is False


class TestTraversalIsNotAPrefixMatch:
    """A raw ``startswith`` check accepts ``<workspace>/../../etc``.

    The workspace string is still a prefix of that path while the real location
    is somewhere else entirely, so containment has to canonicalise first.
    """

    @pytest.mark.parametrize(
        "working_directory",
        [
            WORKSPACE + "/../../../../etc",
            WORKSPACE + "/input/../../../..",
            WORKSPACE + "/./../../root",
        ],
    )
    def test_working_directory_that_climbs_out_is_refused(
        self, policy: CommandPolicy, working_directory: str
    ) -> None:
        decision = policy.validate(("ls", "-la"), working_directory, WORKSPACE)

        assert decision.allowed is False
        assert "outside the workspace" in decision.reason

    def test_a_working_directory_that_lands_back_inside_is_allowed(
        self, policy: CommandPolicy
    ) -> None:
        # Climbing up and back down resolves to the workspace root itself, which
        # is inside the jail. Refusing it would be noise, not safety.
        assert policy.validate(("ls", "-la"), WORKSPACE + "//input/..", WORKSPACE).allowed is True

    def test_a_legitimate_working_directory_still_passes(
        self, policy: CommandPolicy
    ) -> None:
        assert policy.validate(("ls", "-la"), WORKSPACE + "/input", WORKSPACE).allowed is True

    def test_a_sibling_directory_sharing_a_name_prefix_is_refused(
        self, policy: CommandPolicy
    ) -> None:
        decision = policy.validate(("ls", "-la"), WORKSPACE + "-other", WORKSPACE)

        assert decision.allowed is False


class TestOutputPathsCannotEscape:
    """A destination is a write, so the read-only system trees do not apply."""

    @pytest.mark.parametrize(
        "argv",
        [
            ("sort", "-o", "/usr/bin/pwned", "notes.txt"),
            ("sort", "-o/usr/bin/pwned", "notes.txt"),
            ("sort", "--output=/usr/bin/pwned", "notes.txt"),
            ("sort", "--output", "/usr/bin/pwned", "notes.txt"),
        ],
    )
    def test_redirecting_output_into_a_readable_tree_is_refused(
        self, policy: CommandPolicy, argv: tuple[str, ...]
    ) -> None:
        decision = policy.validate(argv, WORKSPACE, WORKSPACE)

        assert decision.allowed is False
        assert "outside the workspace" in decision.reason

    def test_a_relative_output_path_is_refused(
        self, policy: CommandPolicy
    ) -> None:
        # A relative destination resolves against the working directory, which
        # makes it state the workspace path outright instead.
        decision = policy.validate(("sort", "-o", "out.txt", "notes.txt"), WORKSPACE, WORKSPACE)

        assert decision.allowed is False

    def test_output_inside_the_workspace_is_allowed(self, policy: CommandPolicy) -> None:
        argv = ("sort", "-o", WORKSPACE + "/artifacts/sorted.txt", "notes.txt")

        assert policy.validate(argv, WORKSPACE, WORKSPACE).allowed is True

    def test_sort_without_an_output_flag_is_still_allowed(
        self, policy: CommandPolicy
    ) -> None:
        # No -o means sort only writes stdout, which is harmless.
        assert policy.validate(("sort", "notes.txt"), WORKSPACE, WORKSPACE).allowed is True


class TestConfigOverride:
    def test_json_override_replaces_the_allowlist(self) -> None:
        from app.presentation.dependencies.runtime import _commands

        override = _commands('{"ls": ["-l"]}')

        assert override == {"ls": ["-l"]}

    def test_empty_override_means_use_the_defaults(self) -> None:
        from app.presentation.dependencies.runtime import _commands

        assert _commands("   ") is None

    def test_invalid_override_is_a_startup_error(self) -> None:
        from app.presentation.dependencies.runtime import _commands

        with pytest.raises(RuntimeError):
            _commands("not json")

    def test_override_cannot_reach_a_forbidden_command(self) -> None:
        from app.presentation.dependencies.runtime import _commands

        override = _commands('{"rm": ["-rf"]}')
        rebuilt = RuntimeLimitsConfig(
            allowed_commands=override,
            free_argument_commands=tuple(override),
        ).command_policy()

        assert rebuilt.validate(("rm", "-rf", "/"), WORKSPACE, WORKSPACE).allowed is False


class TestDefaultAllowlistShape:
    def test_no_default_command_can_spawn_a_shell(self) -> None:
        # A shell would make every other entry in the allowlist decorative.
        shellish = {"sh", "bash", "zsh", "dash", "python", "perl", "ruby", "node", "env", "printenv"}

        assert not {name for name in DEFAULT_ALLOWED_COMMANDS} & shellish

    def test_find_is_excluded_because_of_exec(self) -> None:
        # `find -exec` runs a second executable the allowlist never sees.
        assert "find" not in DEFAULT_ALLOWED_COMMANDS