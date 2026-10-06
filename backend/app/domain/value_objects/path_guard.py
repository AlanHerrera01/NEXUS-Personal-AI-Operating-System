"""Lexical path canonicalisation for containment checks.

Every "is this path inside the workspace?" question in NEXUS has to answer the
same way, or the strongest check is only as strong as the weakest caller. These
helpers are pure string work on purpose: a policy check must be a decision about
the *declared* path, not about whatever the host happens to have mounted at the
moment. Symlink escapes are a separate concern, closed at the workspace layer
where real paths are resolved before a policy is ever built.

The important property is that ``..`` is resolved against the preceding segment
*before* containment is tested. A plain ``startswith(root)`` on the raw string
accepts ``<workspace>/../../etc``, because the prefix still matches while the
real location is somewhere else entirely.
"""

from __future__ import annotations

import re

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def to_posix(path: str) -> str:
    """Normalise separators so Windows and POSIX callers compare identically."""
    return path.replace("\\", "/")


def canonicalise(path: str) -> str:
    """Collapse separators, ``.`` and ``..`` without touching the filesystem.

    ``..`` that would climb above an absolute root is discarded, because the
    root is the boundary; ``..`` that climbs above a *relative* path is kept,
    because that is the honest reading of the input and it will fail containment
    anyway.
    """
    text = to_posix(path)
    if not text:
        return text

    if text.startswith("//"):
        prefix, text = "//", text[2:]
    elif _WINDOWS_DRIVE.match(text[:2]):
        prefix, text = text[:2], text[2:]
    elif text.startswith("/"):
        prefix, text = "/", text[1:]
    else:
        prefix = ""

    segments: list[str] = []
    for segment in text.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments and segments[-1] != "..":
                segments.pop()
            elif not prefix:
                segments.append("..")
            continue
        segments.append(segment)

    joined = "/".join(segments)
    if prefix == "//":
        return f"//{joined}" if joined else "//"
    if prefix and prefix != "/":
        return f"{prefix}/{joined}" if joined else prefix
    if prefix == "/":
        return f"/{joined}" if joined else "/"
    # Relative input stays relative; inventing a leading slash would turn "not
    # absolute" into "looks rooted" and change what containment decides.
    return joined if joined else "."


def contains(root: str, candidate: str) -> bool:
    """True when ``candidate`` is ``root`` itself or lives underneath it.

    Compares canonicalised forms and requires a separator boundary, so a sibling
    directory that merely shares a name prefix (``/ws/run1evil`` against
    ``/ws/run1``) is not treated as contained.
    """
    base = canonicalise(root).rstrip("/")
    target = canonicalise(candidate)
    if not base or not target:
        return False
    return target == base or target.startswith(base + "/")


def is_absolute(path: str) -> bool:
    text = to_posix(path)
    return text.startswith("/") or bool(_WINDOWS_DRIVE.match(text[:2]))


__all__ = ("canonicalise", "contains", "is_absolute", "to_posix")
