"""Command allowlist.

The agent never gets a shell. It gets the right to ask the runtime to run one
of a small, enumerated set of commands with validated arguments, inside the
workspace, under the session's resource limits. Everything else is denied
before a process is ever created.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.value_objects.path_guard import canonicalise, contains, is_absolute

#: System trees an allowlisted read-only command may reach outside the workspace.
#: ``/etc`` is deliberately absent: it carries host configuration and, on some
#: images, credential material.
SYSTEM_READ_PATHS: tuple[str, ...] = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/opt")

#: Refused regardless of configuration. Matched on the resolved executable.
FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "sudo",
        "su",
        "doas",
        "ssh",
        "scp",
        "sftp",
        "curl",
        "wget",
        "docker",
        "podman",
        "kubectl",
        "helm",
        "nsenter",
        "chroot",
        "mount",
        "umount",
        "dd",
        "mkfs",
        "shutdown",
        "reboot",
        "passwd",
        "chown",
        "chmod",
        "kill",
        "pkill",
        "shutdown",
    }
)

#: Argument fragments that turn an innocent command into an escape.
FORBIDDEN_ARGUMENT_FRAGMENTS: tuple[str, ...] = (
    "..",
    "~",
    "/etc/",
    "/root",
    "/proc/",
    "/dev/",
    "/var/run/",
    "${",
    "$(",
    "`",
    ";",
    "&&",
    "||",
    "|",
    ">",
    "<",
    "\n",
)


@dataclass(frozen=True, slots=True)
class CommandRule:
    """One allowlisted executable and the shape of arguments it accepts."""

    executable: str
    allowed_arguments: tuple[str, ...] = ()
    #: When true, arguments must all appear in ``allowed_arguments``.
    restrict_arguments: bool = True
    #: When true, arguments are checked only against the forbidden-fragment and
    #: path-jail rules. Used for read-only commands such as ``cat`` or ``sort``,
    #: whose arguments are file names the workspace jail already constrains.
    allow_free_arguments: bool = False
    max_arguments: int = 16
    #: Flags whose value is a *write destination* rather than an input. The
    #: value that follows one of these must live inside the workspace, never in a
    #: system tree. Without this, ``sort -o /usr/bin/x file`` reads as an
    #: ordinary read argument and would be allowed to overwrite a host binary.
    write_argument_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("executable must not be empty")
        if self.max_arguments < 1:
            raise ValueError("max_arguments must be at least 1")


@dataclass(frozen=True, slots=True)
class CommandDecision:
    allowed: bool
    reason: str
    rule: CommandRule | None = None

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    """Allowlist consulted before any process is created in a runtime."""

    rules: tuple[CommandRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_spec(
        cls,
        spec: dict[str, Sequence[str] | str],
        free_argument_commands: Sequence[str] = (),
        write_argument_flags: dict[str, Sequence[str]] | None = None,
    ) -> "CommandPolicy":
        """Build a policy from configuration.

        ``free_argument_commands`` names executables whose arguments are file
        names rather than flags. Those skip the exact-flag match but not the
        forbidden-fragment or workspace-jail checks, so ``cat notes.txt`` works
        and ``cat ../../etc/shadow`` still does not.

        ``write_argument_flags`` maps an executable to the flags that name an
        output file, so a command that can redirect its output somewhere else is
        still confined to the workspace.
        """
        free = {name.replace("\\", "/").rsplit("/", 1)[-1] for name in free_argument_commands}
        writers = {
            name.replace("\\", "/").rsplit("/", 1)[-1]: tuple(flags)
            for name, flags in (write_argument_flags or {}).items()
        }
        rules: list[CommandRule] = []
        for executable, arguments in spec.items():
            parsed = shlex.split(arguments) if isinstance(arguments, str) else list(arguments)
            base = executable.replace("\\", "/").rsplit("/", 1)[-1]
            rules.append(
                CommandRule(
                    executable=executable,
                    allowed_arguments=tuple(parsed),
                    restrict_arguments=base not in free,
                    allow_free_arguments=base in free,
                    write_argument_flags=writers.get(base, ()),
                )
            )
        return cls(rules=tuple(rules))

    def executables(self) -> tuple[str, ...]:
        return tuple(rule.executable for rule in self.rules)

    def validate(
        self,
        argv: Sequence[str],
        working_directory: str | None = None,
        workspace_path: str | None = None,
    ) -> CommandDecision:
        """Validate a command. Returns a decision; never raises for user input."""
        if not argv:
            return CommandDecision(False, "empty command")
        executable = argv[0]
        base = executable.replace("\\", "/").rsplit("/", 1)[-1]

        if base in FORBIDDEN_COMMANDS:
            return CommandDecision(False, f"command is never allowed: {base}")
        if base not in {rule.executable for rule in self.rules}:
            return CommandDecision(False, f"command is not in the allowlist: {base}")

        if working_directory and workspace_path:
            # Canonicalise before comparing: a raw prefix check would accept
            # "<workspace>/../../etc", whose string still starts with the
            # workspace but whose real location does not.
            if not contains(workspace_path, working_directory):
                return CommandDecision(False, "working directory is outside the workspace")

        arguments = list(argv[1:])
        rule = next(rule for rule in self.rules if rule.executable == base)
        if len(arguments) > rule.max_arguments:
            return CommandDecision(False, f"too many arguments for {base}")

        root = canonicalise(workspace_path) if workspace_path else ""
        pending_write = False
        for argument in arguments:
            for fragment in FORBIDDEN_ARGUMENT_FRAGMENTS:
                if fragment in argument:
                    return CommandDecision(
                        False, f"argument contains a forbidden sequence: {fragment!r}"
                    )

            consumes_next, embedded = _write_target(rule, argument)
            write_target = embedded if embedded is not None else (
                argument if pending_write else None
            )
            if write_target is not None:
                # An output destination is a write, so only the workspace will
                # do. A system tree is readable but never writable, and a
                # relative destination would resolve against the working
                # directory rather than being stated outright.
                if not is_absolute(write_target):
                    return CommandDecision(
                        False,
                        f"output path must be an absolute workspace path: {write_target}",
                    )
                if root and not contains(root, write_target):
                    return CommandDecision(
                        False, f"output path is outside the workspace: {write_target}"
                    )
            pending_write = consumes_next

            if write_target is None:
                if is_absolute(argument):
                    if root and not _is_readable_path(canonicalise(argument), root):
                        return CommandDecision(
                            False, f"path argument is outside the workspace: {argument}"
                        )
                    if not root:
                        return CommandDecision(
                            False, f"path argument is outside the workspace: {argument}"
                        )

            if (
                rule.restrict_arguments
                and not rule.allow_free_arguments
                and argument not in rule.allowed_arguments
            ):
                return CommandDecision(False, f"argument not allowed for {base}: {argument}")

        return CommandDecision(True, f"{base} is allowlisted", rule=rule)

    def describe(self) -> dict[str, Any]:
        return {rule.executable: list(rule.allowed_arguments) for rule in self.rules}


def _write_target(rule: CommandRule, argument: str) -> tuple[bool, str | None]:
    """Classify ``argument`` against the rule's output flags.

    Returns ``(consumes_next_argument, embedded_value)``:

    * ``-o file`` / ``--output file`` -> ``(True, None)``; the destination is the
      argument that follows.
    * ``-ofile`` / ``--output=file`` -> ``(False, "file")``; the destination is
      embedded in this argument and must be checked right now.
    """
    for flag in rule.write_argument_flags:
        if argument.startswith(f"{flag}="):
            return False, argument[len(flag) + 1 :]
        if argument == flag:
            return True, None
        if not flag.startswith("--") and len(flag) == 2 and argument.startswith(flag):
            return False, argument[len(flag) :]
    return False, None


def _is_readable_path(candidate: str, workspace_root: str) -> bool:
    if contains(workspace_root, candidate):
        return True
    return any(contains(system, candidate) for system in SYSTEM_READ_PATHS)
