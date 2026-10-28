"""A read-only jail for user files.

Everything that touches the filesystem goes through :class:`Workspace`. The
class resolves every path and refuses anything outside its root, follows no
symlinks during discovery, and rejects names that are credentials by convention.
This is intentionally stricter than "the model asked for it".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cfg",
        ".conf",
        ".cpp",
        ".cs",
        ".css",
        ".csv",
        ".go",
        ".h",
        ".hpp",
        ".htm",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".log",
        ".markdown",
        ".md",
        ".php",
        ".ps1",
        ".py",
        ".rb",
        ".rst",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsv",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx"})

SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        ".next",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)

#: Files whose name alone marks them as a credential store. The workspace is
#: read-only, but a read tool that happily opens ``.env`` is an exfiltration
#: primitive with a friendly name.
SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets",
        "secrets.json",
    }
)

SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


class WorkspaceError(Exception):
    """Base class for a refused or failed workspace operation."""


class WorkspaceAccessDenied(WorkspaceError):
    """The path resolves outside the workspace or names a credential."""


class WorkspaceNotFound(WorkspaceError):
    """The path does not exist inside the workspace."""


class WorkspaceFileTooLarge(WorkspaceError):
    """The file exceeds the caller's byte ceiling."""


class WorkspaceUnsupported(WorkspaceError):
    """The file is not text or a document format this build can read."""


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    relative_path: str
    name: str
    size: int
    modified_at: datetime
    suffix: str

    @property
    def is_text(self) -> bool:
        return self.suffix in TEXT_EXTENSIONS

    @property
    def is_document(self) -> bool:
        return self.suffix in DOCUMENT_EXTENSIONS


class Workspace:
    """Resolve relative paths under one root, refusing escapes and secrets."""

    def __init__(self, root: str | Path, *, create: bool = False) -> None:
        self.root = Path(root).expanduser().resolve()
        if create:
            self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str | Path) -> Path:
        raw = str(relative or ".").strip()
        if not raw:
            raw = "."
        candidate = Path(raw)
        if candidate.is_absolute() or candidate.drive:
            raise WorkspaceAccessDenied("absolute paths are not allowed")
        if any(part == ".." for part in candidate.parts):
            raise WorkspaceAccessDenied("parent traversal is not allowed")

        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceAccessDenied("path escapes the workspace")
        self._reject_sensitive(resolved)
        return resolved

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as error:
            raise WorkspaceAccessDenied("path escapes the workspace") from error

    def file(self, relative: str | Path) -> WorkspaceFile:
        path = self.resolve(relative)
        if not path.exists():
            raise WorkspaceNotFound(f"file not found: {self.relative(path)}")
        if not path.is_file():
            raise WorkspaceNotFound(f"not a file: {self.relative(path)}")
        stat = path.stat()
        return WorkspaceFile(
            relative_path=self.relative(path),
            name=path.name,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            suffix=path.suffix.lower(),
        )

    def read_bytes(self, relative: str | Path, *, max_bytes: int) -> tuple[bytes, WorkspaceFile]:
        file = self.file(relative)
        if file.size > max_bytes:
            raise WorkspaceFileTooLarge(
                f"file is larger than the {max_bytes} byte limit: {file.relative_path}"
            )
        return self.resolve(file.relative_path).read_bytes(), file

    def iter_files(
        self,
        relative_dir: str | Path = ".",
        *,
        max_files: int = 5_000,
    ) -> Iterator[WorkspaceFile]:
        base = self.resolve(relative_dir)
        if not base.is_dir():
            raise WorkspaceNotFound(f"not a directory: {self.relative(base)}")

        visited = 0
        for current, directories, filenames in os.walk(base, followlinks=False):
            directories[:] = sorted(
                name
                for name in directories
                if name not in SKIPPED_DIRECTORIES
                and not (Path(current) / name).is_symlink()
            )
            for name in sorted(filenames):
                if visited >= max_files:
                    return
                path = Path(current) / name
                if path.is_symlink():
                    continue
                if self._is_sensitive(path):
                    continue
                if not path.is_file():
                    continue
                visited += 1
                stat = path.stat()
                yield WorkspaceFile(
                    relative_path=self.relative(path),
                    name=path.name,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    suffix=path.suffix.lower(),
                )

    def _reject_sensitive(self, path: Path) -> None:
        if self._is_sensitive(path):
            raise WorkspaceAccessDenied("access to credential-like files is not allowed")

    @staticmethod
    def _is_sensitive(path: Path) -> bool:
        name = path.name.lower()
        if name == ".env.example":
            return False
        if name in SENSITIVE_NAMES or name.startswith(".env."):
            return True
        return any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
