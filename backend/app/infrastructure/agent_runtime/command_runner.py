"""Subprocess seam for the OpenShell adapter.

Isolated behind a protocol so the adapter can be unit-tested without a gateway,
and so a deployment can substitute its own transport. The adapter never builds
a command line; it only ever calls this runner with an already-validated argv
list, so there is no shell interpolation anywhere in the runtime path.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.infrastructure.agent_runtime.exceptions import OpenShellNotInstalledError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class CommandRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...

    def is_available(self, executable: str) -> bool: ...


class SubprocessCommandRunner:
    """Runs an argv list with no shell, so no argument can be reinterpreted."""

    def __init__(self, default_timeout: float = 120.0) -> None:
        self.default_timeout = default_timeout

    def is_available(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        if not argv:
            raise OpenShellNotInstalledError("empty command")
        if not self.is_available(argv[0]):
            raise OpenShellNotInstalledError(f"executable is not on PATH: {argv[0]}")

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            shell=False,
        )
        try:
            out, err = await asyncio.wait_for(
                process.communicate(input=stdin.encode("utf-8") if stdin is not None else None),
                timeout=timeout or self.default_timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("command timed out: %s", argv[0])
            return CommandResult(tuple(argv), 124, "", "timeout", timed_out=True)

        return CommandResult(
            argv=tuple(argv),
            exit_code=process.returncode if process.returncode is not None else 1,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
        )
