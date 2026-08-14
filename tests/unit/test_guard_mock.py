"""spec10 §4.4 rung 3 / issue #145 — guard-aware mocks.

The whole point of this rung is the trap: a plain MagicMock is truthy, and so
is every attribute read off it. `MagicMock(spec=Team)` passed to

    if not team.owner_id:
        raise ValueError(...)

makes the guard stop firing, so the generated test exercises nothing. It would
pass Gate 4 for the wrong reason and be rejected by Gate 5.

These tests pin that the mock sets the attribute the guard actually reads.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quell.synthesis import guard_mock

# ── guard parsing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "obj", "attr"),
    [
        ("if not team.owner_id:", "team", "owner_id"),
        ("if team.owner_id is None:", "team", "owner_id"),
        ("if not user.email:", "user", "email"),
    ],
)
def test_parses_single_attribute_guards(raw: str, obj: str, attr: str):
    g = guard_mock.parse_guard(raw)
    assert g is not None
    assert (g.obj, g.attr) == (obj, attr)


def test_ignores_self_attributes():
    """`self.x` is the instance under test, not a parameter we can mock."""
    assert guard_mock.parse_guard("if not self.client:") is None


def test_ignores_compound_conditions():
    """Ambiguous which side to violate — better to decline than guess."""
    assert guard_mock.parse_guard("if not a.x and not b.y:") is None
    assert guard_mock.parse_guard("if a.x or b.y:") is None


def test_ignores_non_attribute_guards():
    assert guard_mock.parse_guard("if user_id <= 0:") is None
    assert guard_mock.parse_guard(None) is None


def test_violating_value_matches_guard_shape():
    assert guard_mock.parse_guard("if not team.owner_id:").violating == "None"
    assert guard_mock.parse_guard("if len(team.name) < 3:").violating == '""'
    assert guard_mock.parse_guard("if team.count < 1:").violating == "0"


# ── expression building ──────────────────────────────────────────────────────


def test_declines_without_a_guard():
    """No guard attribute ⇒ an all-truthy mock that cannot make anything fire.

    Emitting it would waste two pytest runs and land in the rejected bucket.
    """
    assert guard_mock.build("Team", "app.models", None) is None


def test_expression_is_valid_and_self_contained():
    g = guard_mock.parse_guard("if not team.owner_id:")
    expr = guard_mock.build("Team", "app.models", g)
    assert expr is not None
    compile(expr, "<test>", "eval")
    assert "MagicMock" in expr
    assert "owner_id=None" in expr
    assert "spec=" in expr


def test_works_without_a_resolvable_type():
    """Unknown module ⇒ still emit a mock, just unspec'd."""
    g = guard_mock.parse_guard("if not team.owner_id:")
    expr = guard_mock.build(None, None, g)
    assert expr is not None
    assert "spec=" not in expr
    assert "owner_id=None" in expr


# ── the behaviour that matters ───────────────────────────────────────────────


def test_plain_mock_would_not_fire_the_guard():
    """Documents the trap this module exists to avoid."""
    plain = MagicMock()
    assert bool(plain.owner_id) is True          # truthy ⇒ `if not` never fires


def test_guard_aware_mock_does_fire_the_guard():
    g = guard_mock.parse_guard("if not team.owner_id:")
    expr = guard_mock.build(None, None, g)
    team = eval(expr)  # noqa: S307 — expression is generated and compiled above
    assert team.owner_id is None
    assert not team.owner_id                     # the guard fires


def test_mock_still_supports_other_attribute_access():
    """Only the guarded attribute is pinned; the rest stays mock-like."""
    g = guard_mock.parse_guard("if not team.owner_id:")
    team = eval(guard_mock.build(None, None, g))  # noqa: S307
    assert team.owner_id is None
    assert team.anything_else is not None
