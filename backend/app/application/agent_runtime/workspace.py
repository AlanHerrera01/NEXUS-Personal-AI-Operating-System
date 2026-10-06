"""Filesystem jail for runtime sessions.

One workspace per agent run, four fixed subdirectories, no traversal. The
workspace is the only writable location a runtime is ever granted, and it is
not the filesystem, the home directory, or any credential store.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.domain.value_objects.entity_id import EntityId

logger = logging.getLogger(__name__)

SUBDIRECTORIES: tuple[str, ...] = ("input", "output", "temp", "artifacts")


class WorkspaceError(RuntimeError):
    """Raised when a workspace path escapes its root or cannot be created."""


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """Creates and removes per-run workspaces under a single controlled root."""

    root: Path
    agent_workspace_dirname: str = "agent-workspace"
    create: bool = True

    def __post_init__(self) -> None:
        if not str(self.root).strip():
            raise WorkspaceError("workspace root must not be empty")

    @property
    def root_path(self) -> Path:
        return Path(self.root).expanduser().resolve()

    def run_directory(self, agent_run_id: EntityId) -> Path:
        return self.root_path / self.agent_workspace_dirname / str(agent_run_id)

    def sandbox_name(self, agent_run_id: EntityId) -> str:
        return f"nexus-{agent_run_id}"

    def prepare(self, agent_run_id: EntityId) -> str:
        """Create the four subdirectories and return the absolute workspace path."""
        base = self.run_directory(agent_run_id)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise WorkspaceError(f"cannot create workspace: {base}") from error
        for name in SUBDIRECTORIES:
            (base / name).mkdir(parents=True, exist_ok=True)
        if self.create:
            (base / ".nexus-workspace").write_text(
                f"agent_run_id={agent_run_id}\n", encoding="utf-8"
            )
        return str(base)

    def subdirectory(self, agent_run_id: EntityId, name: str) -> Path:
        if name not in SUBDIRECTORIES:
            raise WorkspaceError(f"unknown workspace subdirectory: {name}")
        return self.run_directory(agent_run_id) / name

    def resolve_inside(self, agent_run_id: EntityId, relative: str) -> Path:
        """Resolve a relative path inside the workspace, refusing any escape."""
        base = self.run_directory(agent_run_id).resolve()
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as error:
            raise WorkspaceError(f"path escapes the workspace: {relative}") from error
        return candidate

    def is_inside(self, agent_run_id: EntityId, path: str) -> bool:
        try:
            self.resolve_inside(agent_run_id, os.path.relpath(Path(path), self.run_directory(agent_run_id)))
        except (WorkspaceError, ValueError):
            return False
        return True

    def discard(self, agent_run_id: EntityId) -> None:
        base = self.run_directory(agent_run_id)
        if not base.exists():
            return
        # Refuse to delete anything that is not a workspace we created.
        if self.agent_workspace_dirname not in base.parts:
            raise WorkspaceError(f"refusing to remove a path outside the workspace root: {base}")
        try:
            shutil.rmtree(base)
        except OSError:  # noqa: BLE001 - cleanup is best effort by design
            logger.warning("could not remove workspace %s", base)

    def purge(self) -> int:
        """Remove every workspace. Used by teardown tooling, never mid-run."""
        removed = 0
        base = self.root_path / self.agent_workspace_dirname
        if not base.exists():
            return 0
        for entry in base.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed
