"""spec10 §4.6 / issue #153 — each ladder rung must be independently disablable.

Without this the bake-off cannot attribute yield to anything: every arm would
run the same engine and the table would show four identical rows.

The default must stay "everything on" — nothing in normal operation passes
`strategies`, and a regression that flipped the default would silently disable
the ladder in production while these ablation tests still passed.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quell.synthesis import fixture_locator
from quell.synthesis.rule_engine import RuleEngine


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text(
        textwrap.dedent(
            """
            import pytest

            @pytest.fixture
            def db_session():
                yield None
            """
        ).strip(),
        encoding="utf-8",
    )
    fixture_locator._find_fixtures_cached.cache_clear()
    return tmp_path


def test_default_enables_every_rung():
    """Production behaviour: no caller passes `strategies`."""
    engine = RuleEngine()
    assert engine._strategies == RuleEngine.ALL_STRATEGIES
    assert {"fixtures", "constructions", "guard_mocks"} <= engine._strategies


def test_empty_strategies_disables_fixture_lookup(project: Path):
    """A0 in the bake-off — pre-spec10 behaviour, literal stubs only."""
    engine = RuleEngine(project_root=project, strategies=frozenset())
    assert engine._project_fixtures(None) == {}


def test_fixtures_rung_can_be_enabled_alone(project: Path):
    engine = RuleEngine(project_root=project, strategies={"fixtures"})
    assert "db_session" in engine._project_fixtures(None)


def test_constructions_rung_is_independently_gated(project: Path):
    with_it = RuleEngine(project_root=project, strategies={"constructions"})
    without = RuleEngine(project_root=project, strategies={"fixtures"})
    # Not asserting contents — only that the gate is honoured, since an empty
    # project legitimately mines nothing.
    assert without._project_constructions(None) == {}
    assert isinstance(with_it._project_constructions(None), dict)


def test_no_project_root_means_no_strategies_regardless(project: Path):
    """The explicit-root discipline from #157 still holds under ablation."""
    engine = RuleEngine(strategies=RuleEngine.ALL_STRATEGIES)
    assert engine._project_fixtures(None) == {}
    assert engine._project_constructions(None) == {}


def test_arms_are_cumulative_and_distinct():
    """The harness's arms must actually differ, or the table means nothing."""
    from benchmarks.ablation import ARMS

    sets = [s for _, s in ARMS]
    assert sets[0] == frozenset()
    for earlier, later in zip(sets, sets[1:]):
        assert earlier < later, "each arm must add exactly one rung"
    assert sets[-1] == RuleEngine.ALL_STRATEGIES
