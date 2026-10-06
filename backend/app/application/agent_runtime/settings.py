"""Runtime configuration.

Kept in the application layer as a plain dataclass so the policy factory has no
dependency on Pydantic, FastAPI or the settings singleton. The composition root
in ``app.presentation.dependencies`` converts ``Settings`` into this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.domain.value_objects.command_policy import CommandPolicy

#: Read-only, non-interactive commands. Nothing here can spawn a shell, start a
#: network client, or read a file outside the workspace.
#:
#: Deliberately absent: ``env``/``printenv`` (dump the credential-bearing
#: environment into model-visible output) and ``python -c``/``sh -c`` (arbitrary
#: code, which would make the whole allowlist decorative).
DEFAULT_ALLOWED_COMMANDS: dict[str, Sequence[str]] = {
    "ls": ("-la", "-l", "-a", "--all"),
    "wc": ("-l", "-w", "-c"),
    "cat": (),
    "head": ("-n",),
    "tail": ("-n",),
    "sort": (),
    "uniq": ("-c",),
    "cut": ("-d", "-f", "-c"),
    "diff": (),
    "grep": ("-c", "-o", "-i", "-n"),
    "sha256sum": (),
}

#: ``find`` is intentionally not in the default allowlist: its ``-exec`` runs a
#: second executable that the allowlist never sees, so it would sidestep
#: ``allowed_binaries`` entirely. A deployment that wants it should say so
#: explicitly and accept that it also allows process spawning.

#: Flags that name an output *file* rather than an input. The value that
#: follows one of these is a write destination, so it is confined to the
#: workspace even when the same command may freely read system trees.
#:
#: Without this declaration ``sort -o /usr/bin/pwned notes.txt`` parses as two
#: ordinary arguments: ``/usr/bin/pwned`` sits in a readable system tree, so the
#: read rule lets it through and the agent overwrites a host binary. ``sort``
#: with no ``-o`` only writes stdout and stays safe.
WRITE_ARGUMENT_FLAGS: dict[str, tuple[str, ...]] = {
    "sort": ("-o", "--output"),
}

#: Commands whose arguments are file names, patterns and flags rather than a
#: fixed enumeration. Flag allowlisting is deliberately not enforced for these:
#: the properties that are actually enforceable here are (a) no shell is ever
#: spawned, (b) no shell metacharacter or traversal can appear in an argument,
#: (c) absolute paths must fall inside the workspace or a read-only system tree,
#: and (d) an output path must fall inside the workspace. Hardening further is
#: the runtime's job (Landlock + the sandbox policy), which is why
#: ``allowed_binaries`` still bounds what may run at all.
FREE_ARGUMENT_COMMANDS: tuple[str, ...] = tuple(DEFAULT_ALLOWED_COMMANDS)


@dataclass(frozen=True, slots=True)
class RuntimeLimitsConfig:
    """Every ceiling is configuration. Nothing here is a magic number."""

    max_execution_seconds: float = 30.0
    max_output_bytes: int = 262_144
    max_memory_mb: int = 512
    max_cpu: str = "1"
    max_filesystem_bytes: int = 67_108_864
    max_network_requests: int = 16
    max_tool_calls: int = 10
    max_processes: int = 64
    expiration_seconds: int = 900
    read_only_paths: tuple[str, ...] = ()
    #: (host, port, access) triples the runtime may reach.
    allowed_network_endpoints: tuple[tuple[str, int, str], ...] = ()
    allowed_binaries: tuple[str, ...] = ("/usr/bin/ls", "/usr/bin/cat", "/usr/bin/wc", "/usr/bin/sort")
    allowed_commands: dict[str, Sequence[str]] = field(
        default_factory=lambda: dict(DEFAULT_ALLOWED_COMMANDS)
    )
    free_argument_commands: tuple[str, ...] = FREE_ARGUMENT_COMMANDS
    write_argument_flags: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(WRITE_ARGUMENT_FLAGS)
    )
    #: Wall-clock ceiling for the runtime *driver* (the CLI or jail helper), as
    #: opposed to ``max_execution_seconds``, which bounds the workload.
    #:
    #: The two must be different numbers. The driver needs time to start a
    #: sandbox, apply a policy and stream output back, so it is necessarily
    #: longer than the workload it carries. Collapsing them would either kill
    #: the driver mid-negotiation or let the workload outlive its budget.
    command_timeout_seconds: float = 120.0

    def command_policy(self) -> CommandPolicy:
        return CommandPolicy.from_spec(
            self.allowed_commands, self.free_argument_commands, self.write_argument_flags
        )
