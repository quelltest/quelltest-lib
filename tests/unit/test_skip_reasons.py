"""spec10 non-negotiable #6 / issue #148 — every skip is typed and reported.

The rule engine had eleven bare `return None` paths. Each turned a visible
failure into a silent one, so local pass-rate rose while the addressable set
quietly shrank — which is what "0 of 17 in teams.py" was actually reporting.

These tests pin that no skip is silent, and that the reason identifies which
rung of the §4.4 ladder the case is waiting on.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from quell.core.models import ConstraintKind, Requirement, SkipReason, SpecSource
from quell.synthesis.rule_engine import RuleEngine


def _req(tmp_path: Path, body: str, kind: ConstraintKind, raw: str = "") -> Requirement:
    src = tmp_path / "svc.py"
    src.write_text(body, encoding="utf-8")
    return Requirement(
        id="r1",
        source=SpecSource.CODE_GUARD,
        description="test requirement",
        constraint_kind=kind,
        target_function="handle",
        target_file=src,
        raw_spec_text=raw,
    )


# ── the structural guarantee ─────────────────────────────────────────────────


def test_no_bare_return_none_remains_in_rule_engine():
    """Only _skip() itself and its documented pass-through may return None."""
    import quell.synthesis.rule_engine as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    bare = [
        (i + 1, ln.strip())
        for i, ln in enumerate(source.splitlines())
        if re.match(r"\s*return None\b", ln)
    ]
    # _skip's own `return None`, and generate()'s annotated pass-through.
    assert len(bare) == 2, f"unexpected bare skips: {bare}"
    assert any("last_skip" in ln for _, ln in bare)


def test_every_skip_reason_has_a_human_readable_value():
    for reason in SkipReason:
        assert reason.value and " " in reason.value, reason.name


# ── reasons are actually recorded ────────────────────────────────────────────


def test_self_attribute_guard_is_typed(tmp_path: Path):
    engine = RuleEngine()
    req = _req(
        tmp_path,
        "def handle(x):\n    if not x:\n        return None\n",
        ConstraintKind.NOT_NULL,
        raw="if not self.client:",
    )
    assert engine.generate(req) is None
    assert engine.last_skip == SkipReason.SELF_ATTRIBUTE_GUARD


def test_optional_return_is_typed(tmp_path: Path):
    engine = RuleEngine()
    req = _req(
        tmp_path,
        "def handle(x: int) -> str | None:\n    return None\n",
        ConstraintKind.MUST_RETURN,
    )
    assert engine.generate(req) is None
    assert engine.last_skip == SkipReason.OPTIONAL_RETURN


def test_module_state_guard_is_typed(tmp_path: Path):
    engine = RuleEngine()
    req = _req(
        tmp_path,
        "def handle(x: int):\n    assert ujson is not None\n    return x\n",
        ConstraintKind.CUSTOM,
        raw="assert ujson is not None",
    )
    assert engine.generate(req) is None
    assert engine.last_skip == SkipReason.MODULE_STATE_GUARD


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_last_skip_is_cleared_on_each_generate(tmp_path: Path):
    """A stale reason must not survive into a later, successful call."""
    engine = RuleEngine()

    skipped = _req(
        tmp_path,
        "def handle(x):\n    if not x:\n        return None\n",
        ConstraintKind.NOT_NULL,
        raw="if not self.client:",
    )
    assert engine.generate(skipped) is None
    assert engine.last_skip is not None

    ok = _req(
        tmp_path,
        "def handle(amount: int):\n    if amount <= 0:\n        raise ValueError('bad')\n    return amount\n",
        ConstraintKind.BOUNDARY,
        raw="if amount <= 0:",
    )
    result = engine.generate(ok)
    if result is not None:
        assert engine.last_skip is None, "stale skip reason survived a success"


@pytest.mark.parametrize("reason", list(SkipReason))
def test_skip_helper_records_and_declines(reason: SkipReason):
    engine = RuleEngine()
    assert engine._skip(reason) is None
    assert engine.last_skip == reason
