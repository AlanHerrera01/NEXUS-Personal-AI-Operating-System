"""The Always-On configuration surface is documented, and the docs are correct.

A renamed setting keeps its old name in ``.env.example`` and the design note, and
nothing fails until an operator sets a variable that no longer does anything.
Asserting the three agree turns that into a build failure.
"""

import re
from pathlib import Path

import pytest

from app.config.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
ENV_EXAMPLE = BACKEND / ".env.example"
DOC_SOURCES = [ENV_EXAMPLE, REPO / "docs" / "always_on.md"]


def _documented_names() -> set[str]:
    """Setting names mentioned in either source, normalised to lowercase.

    `.env.example` spells them uppercase because that is how the environment
    spells them; the design note spells them lowercase because that is how
    `Settings` does. Matching only one case silently checks half the surface.
    """
    names: set[str] = set()
    for source in DOC_SOURCES:
        assert source.exists(), f"missing documentation source: {source}"
        text = source.read_text(encoding="utf-8")
        names.update(
            token.lower()
            for token in re.findall(r"always_on_[A-Za-z_]+", text, re.IGNORECASE)
        )
    return names


def _real_names() -> set[str]:
    return {name for name in Settings.model_fields if name.startswith("always_on_")}


@pytest.mark.integration
def test_every_always_on_setting_is_documented() -> None:
    undocumented = sorted(_real_names() - _documented_names())
    assert not undocumented, (
        "Always-On settings missing from .env.example and/or docs/always_on.md: "
        + ", ".join(undocumented)
    )


@pytest.mark.integration
def test_docs_name_no_setting_that_does_not_exist() -> None:
    invented = sorted(_documented_names() - _real_names())
    assert not invented, (
        "Documentation references Always-On settings that do not exist in "
        f"Settings: {', '.join(invented)}"
    )


def test_env_example_does_not_enable_always_on_or_webhook_ingress() -> None:
    """A template that ships an open webhook would be a security incident.

    Copied to `.env` far more often than it is read, so the shipped defaults are
    asserted rather than trusted.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^ALWAYS_ON_ENABLED=false$", text, re.MULTILINE)
    assert re.search(r"^ALWAYS_ON_EVENT_INGRESS_SECRET=\s*$", text, re.MULTILINE)