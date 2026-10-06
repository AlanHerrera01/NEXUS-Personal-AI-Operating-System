"""Secret detection and redaction.

Used in three places, and the same rules in all three, because a secret that is
redacted in one path and not in another is a secret that leaks:

* before content is written to memory, so a key pasted into a conversation is
  refused rather than stored and replayed into future prompts;
* on the way into an audit entry or a log line;
* before external content is handed to the model, so a credential that arrived
  inside a web page or a tool result is not echoed back in a prompt.

The patterns are heuristics over *shapes*, not a keyring. Nothing here can prove
a string is not a credential, which is why the memory path is fail-closed on a
match and the log path redacts rather than refuses. The false-positive cost is
deliberately asymmetric: refusing to remember a string that merely looks like a
key is a minor inconvenience, and storing one is a credential at rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Deliberately narrow: enough to catch a pasted credential, few enough not to
#: mangle ordinary prose. Each entry is (name, compiled pattern).
#:
#: Vendor key formats first, because those are the ones that are unambiguously
#: credentials and appear most often in leaked configuration.
_VENDOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("hugging_face_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("nebius_api_key", re.compile(r"\bnemotron-[A-Za-z0-9_\-]{16,}\b")),
)

#: Key/value shapes. Require the secret-ish name *and* a plausible value so that
#: "password: please enter your password" is not flagged.
_NAMED_SECRET = re.compile(
    r"(?i)\b("
    r"api[_\-]?key|apikey|secret[_\-]?key|secret|access[_\-]?key|"
    r"access[_\-]?token|auth[_\-]?token|refresh[_\-]?token|bearer[_\-]?token|"
    r"client[_\-]?secret|private[_\-]?key|passwd|password|passphrase|"
    r"database[_\-]?url|connection[_\-]?string"
    r")\b\s*[:=]\s*[\"']?([^\s\"',;]{8,})"
)

#: PEM blocks. The header alone is enough signal.
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

#: ``user:password@host`` inside a connection URL.
_URL_CREDENTIALS = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s:/@]{3,})@")

REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """One suspected credential. Carries its *kind*, never its value."""

    kind: str
    #: Character offset of the match, so a caller can report where it was
    #: without reproducing what was there.
    offset: int

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.kind} at offset {self.offset}"


def find_secrets(text: str) -> list[SecretFinding]:
    """Every suspected credential in ``text``. Order is by position."""
    if not text:
        return []

    findings: list[SecretFinding] = []
    for kind, pattern in _VENDOR_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(SecretFinding(kind, match.start()))

    if _PEM.search(text):
        findings.append(SecretFinding("private_key", _PEM.search(text).start()))

    for match in _NAMED_SECRET.finditer(text):
        findings.append(SecretFinding(f"named:{match.group(1).lower()}", match.start()))

    for match in _URL_CREDENTIALS.finditer(text):
        findings.append(SecretFinding("url_credentials", match.start(1)))

    findings.sort(key=lambda finding: finding.offset)
    return findings


def contains_secret(text: str) -> bool:
    """True when ``text`` looks like it carries a credential."""
    return bool(find_secrets(text))


def redact(text: str) -> str:
    """Replace every suspected credential with a fixed marker.

    The marker is constant rather than length-preserving on purpose: a
    length-preserving mask would still leak how long the secret is.
    """
    if not text:
        return text

    for _, pattern in _VENDOR_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _PEM.sub(f"-----BEGIN PRIVATE KEY----- {REDACTED}", text)
    text = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    text = _URL_CREDENTIALS.sub(
        lambda match: match.group(0).replace(match.group(1), REDACTED), text
    )
    return text


def redact_mapping(mapping: dict[str, str] | None) -> dict[str, str] | None:
    """Redact both keys and values of a mapping."""
    if mapping is None:
        return None
    return {redact(str(key)): redact(str(value)) for key, value in mapping.items()}


def describe_findings(findings: list[SecretFinding]) -> str:
    """A safe, loggable summary: kinds and counts, never values."""
    if not findings:
        return "none"
    kinds: dict[str, int] = {}
    for finding in findings:
        kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
    return ", ".join(f"{kind} x{count}" for kind, count in sorted(kinds.items()))


__all__ = (
    "REDACTED",
    "SecretFinding",
    "contains_secret",
    "describe_findings",
    "find_secrets",
    "redact",
    "redact_mapping",
)