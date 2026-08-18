"""spec10 §4.2 / issue #154 — rank gaps so the default list is actionable.

The number being fixed: a QA pass got 170 flagged items and found 3 genuine
holes by hand. ~1.8% actionable, against a Tricorder abandonment threshold
near 10%.

The rule these tests protect: truncate the DISPLAY, never the analysis.
Nothing is dropped, and every suppressed item keeps the reason it was
suppressed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.models import ConstraintKind, Requirement, SpecSource
from quell.coverage.ranker import (
    DEFAULT_DISPLAY_LIMIT,
    Suppression,
    actionable,
    public_names_for,
    rank,
    surfaced_ratio,
)
from quell.coverage.runtime import CoverageMap


def _req(name: str, line: int = 10, kind=ConstraintKind.NOT_NULL) -> Requirement:
    return Requirement(
        id=f"r-{name}-{line}",
        source=SpecSource.CODE_GUARD,
        description="guard",
        constraint_kind=kind,
        target_function=name,
        target_file=Path("app/svc.py"),
        source_line=line,
    )


# ── suppression ──────────────────────────────────────────────────────────────


def test_measured_execution_suppresses_a_gap():
    """The strongest signal: an existing test already runs this line."""
    cmap = CoverageMap(lines={Path("app/svc.py").resolve(): {10: {"tests/t.py::test_a"}}})
    [g] = rank([_req("charge", 10)], coverage_map=cmap)

    assert g.suppressed_by is Suppression.ALREADY_EXERCISED
    assert g.is_actionable is False
    assert g.reasons  # never suppressed without saying why


def test_unexercised_line_stays_actionable():
    cmap = CoverageMap(lines={Path("app/svc.py").resolve(): {99: {"tests/t.py::test_a"}}})
    [g] = rank([_req("charge", 10)], coverage_map=cmap)
    assert g.is_actionable is True


def test_private_uncalled_function_is_suppressed():
    [g] = rank([_req("_helper")], public_names=set(), callers={})
    assert g.suppressed_by is Suppression.PRIVATE_UNCALLED


def test_private_but_called_is_not_suppressed():
    [g] = rank([_req("_helper")], callers={"_helper": 3})
    assert g.is_actionable is True


def test_broken_coverage_map_does_not_hide_gaps():
    """A bad map must fail open — hiding a real gap is worse than noise."""

    class Broken:
        def is_line_covered(self, *_a, **_k):
            raise RuntimeError("corrupt")

    [g] = rank([_req("charge")], coverage_map=Broken())
    assert g.is_actionable is True


# ── ranking ──────────────────────────────────────────────────────────────────


def test_public_api_outranks_private():
    gaps = rank(
        [_req("_internal"), _req("charge")],
        public_names={"charge"},
        callers={"_internal": 1},
    )
    assert gaps[0].requirement.target_function == "charge"


def test_higher_fan_in_ranks_higher():
    gaps = rank(
        [_req("rarely"), _req("often")],
        public_names={"rarely", "often"},
        callers={"rarely": 1, "often": 5},
    )
    assert gaps[0].requirement.target_function == "often"


def test_actionable_items_come_before_suppressed():
    cmap = CoverageMap(lines={Path("app/svc.py").resolve(): {10: {"t"}}})
    gaps = rank([_req("covered", 10), _req("uncovered", 20)], coverage_map=cmap)
    assert gaps[0].requirement.target_function == "uncovered"
    assert gaps[-1].suppressed_by is Suppression.ALREADY_EXERCISED


# ── the contract that matters ────────────────────────────────────────────────


def test_nothing_is_dropped():
    """Truncate the display, never the analysis."""
    cmap = CoverageMap(lines={Path("app/svc.py").resolve(): {10: {"t"}}})
    reqs = [_req(f"f{i}", 10) for i in range(20)] + [_req("real", 55)]
    gaps = rank(reqs, coverage_map=cmap)
    assert len(gaps) == len(reqs)


def test_surfaced_ratio_reports_suppression_rate():
    cmap = CoverageMap(lines={Path("app/svc.py").resolve(): {10: {"t"}}})
    reqs = [_req(f"f{i}", 10) for i in range(9)] + [_req("real", 55)]
    gaps = rank(reqs, coverage_map=cmap)

    assert len(actionable(gaps)) == 1
    assert surfaced_ratio(gaps) == pytest.approx(0.1)
    assert surfaced_ratio([]) == 0.0


def test_default_display_limit_is_sane():
    assert 1 <= DEFAULT_DISPLAY_LIMIT <= 25


# ── public surface detection ─────────────────────────────────────────────────


def test_public_names_skips_private_and_tests(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def charge(): pass\ndef _helper(): pass\n", encoding="utf-8"
    )
    (tmp_path / "test_app.py").write_text("def test_charge(): pass\n", encoding="utf-8")

    names = public_names_for(tmp_path)
    assert "charge" in names
    assert "_helper" not in names
    assert "test_charge" not in names


def test_public_names_survives_malformed_source(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    assert public_names_for(tmp_path) == set()  # invariant #6


# ── control-flow exits (the noise G3_MEASUREMENT.md identified) ──────────────


def _raise_req(desc: str) -> Requirement:
    return Requirement(
        id="r-cf",
        source=SpecSource.CODE_GUARD,
        description=desc,
        constraint_kind=ConstraintKind.MUST_RAISE,
        target_function="cmd_pr",
        target_file=Path("quell/cli.py"),
        source_line=10,
    )


@pytest.mark.parametrize(
    "desc",
    [
        "raises typer.Exit when Exception occurs — except Exception as e:",
        "raises Exit when Exception occurs — except Exception:",
        "raises SystemExit when OSError occurs — except OSError:",
        "raises click.Abort when Exception occurs — except Exception:",
    ],
)
def test_process_control_exceptions_are_suppressed(desc: str):
    """`except Exception: raise typer.Exit(1)` is a CLI exiting, not a contract."""
    [g] = rank([_raise_req(desc)])
    assert g.suppressed_by is Suppression.CONTROL_FLOW_EXIT


@pytest.mark.parametrize(
    "desc",
    [
        "raises ValueError when KeyError occurs — except KeyError:",
        "raises QuellAuthError when HTTPError occurs — except HTTPError:",
        "raises PermissionError when OSError occurs — except OSError:",
    ],
)
def test_real_error_contracts_are_not_suppressed(desc: str):
    """Exception translation IS a contract worth testing — must survive."""
    [g] = rank([_raise_req(desc)])
    assert g.is_actionable is True


def test_non_raise_descriptions_are_unaffected():
    [g] = rank([_req("charge")])
    assert g.suppressed_by is not Suppression.CONTROL_FLOW_EXIT


def test_exercised_line_keeps_its_more_specific_reason():
    """Stronger signals win — a covered guard reports coverage, not exit."""
    cmap = CoverageMap(lines={Path("quell/cli.py").resolve(): {10: {"t"}}})
    [g] = rank([_raise_req("raises typer.Exit when Exception occurs")], coverage_map=cmap)
    assert g.suppressed_by is Suppression.ALREADY_EXERCISED
