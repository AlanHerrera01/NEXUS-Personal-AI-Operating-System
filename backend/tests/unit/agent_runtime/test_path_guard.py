"""Containment is a shared invariant, so it is tested in one place."""

from __future__ import annotations

import pytest

from app.domain.value_objects.path_guard import canonicalise, contains, is_absolute


class TestCanonicalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/srv/ws/../etc", "/srv/etc"),
            ("/srv/ws/../../etc", "/etc"),
            ("/srv//ws///input", "/srv/ws/input"),
            ("/srv/ws/./input", "/srv/ws/input"),
            ("/srv/ws/", "/srv/ws"),
            ("C:\\Users\\a\\..\\b", "C:/Users/b"),
            ("//server/share/../x", "//server/x"),
        ],
    )
    def test_separators_dots_and_dotdot_collapse(self, raw: str, expected: str) -> None:
        assert canonicalise(raw) == expected

    def test_dotdot_above_an_absolute_root_is_discarded(self) -> None:
        # The root is the boundary; there is nothing above it to climb to.
        assert canonicalise("/../../etc") == "/etc"

    def test_dotdot_above_a_relative_path_is_kept(self) -> None:
        # Honest reading of the input, and it fails containment anyway.
        assert canonicalise("../etc") == "../etc"

    def test_empty_path_stays_empty(self) -> None:
        assert canonicalise("") == ""


class TestContains:
    def test_root_contains_itself(self) -> None:
        assert contains("/srv/ws", "/srv/ws") is True

    def test_descendant_is_contained(self) -> None:
        assert contains("/srv/ws", "/srv/ws/input/a.txt") is True

    @pytest.mark.parametrize(
        "candidate",
        [
            "/srv/ws/../../etc",
            "/srv/ws-evil/a.txt",
            "/srv/other",
            "/etc/passwd",
            "/srv/wsX",
        ],
    )
    def test_non_descendants_are_refused(self, candidate: str) -> None:
        assert contains("/srv/ws", candidate) is False

    def test_traversal_is_resolved_before_comparison(self) -> None:
        # This is the exact case a raw prefix check would wave through.
        assert contains("/srv/ws", "/srv/ws/../../etc") is False

    def test_empty_inputs_are_never_contained(self) -> None:
        assert contains("", "/srv/ws") is False
        assert contains("/srv/ws", "") is False


class TestIsAbsolute:
    @pytest.mark.parametrize("value", ["/srv/ws", "C:/Users", "C:\\Users"])
    def test_absolute_paths(self, value: str) -> None:
        assert is_absolute(value) is True

    @pytest.mark.parametrize("value", ["notes.txt", "./a", "../a", "ws/a.txt"])
    def test_relative_paths(self, value: str) -> None:
        assert is_absolute(value) is False
