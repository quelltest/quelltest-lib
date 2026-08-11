"""spec10 §4.1 — metric validity regression tests.

The failure these lock down: two independent Claude Code sessions ran quelltest
against a production backend with a 106-test suite, got 0/100, added real
passing tests, still got 0/100, and one uninstalled the library. The PRS
numerator counted only tests quelltest itself wrote.

Every test here fails against pre-spec10 `main`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.confidence.prs import compute_prs
from quell.core.models import BucketedResult, OutputBucket
from quell.coverage.checker import CoverageChecker
from quell.spec.code_guard_reader import CodeGuardReader

FIXTURE = Path(__file__).parent.parent / "fixtures" / "handwritten_suite_project"


# ── the headline regression ──────────────────────────────────────────────────


def test_handwritten_suite_does_not_score_zero():
    """A fully hand-tested project with ZERO quelltest-written tests scores > 0."""
    reqs = CodeGuardReader().read(FIXTURE / "src" / "billing.py")
    assert reqs, "fixture must yield guard-clause requirements"

    checker = CoverageChecker(FIXTURE)
    checked = checker.check(reqs)
    covered = [r for r in checked if r.is_covered]
    gaps = [r for r in checked if not r.is_covered]

    assert covered, "hand-written suite in tests/integration/ must be discovered"

    # quelltest wrote nothing: every gap is FLAGGED, none WRITTEN.
    results = [
        BucketedResult(requirement_id=r.id, bucket=OutputBucket.FLAGGED)
        for r in gaps
    ]
    prs = compute_prs(
        results,
        covered_count=len(covered),
        coverage_known=checker.has_test_suite,
    )

    assert prs.scored is True
    assert prs.score > 0, (
        "hand-written tests must count toward the score — this is the exact "
        "failure that lost a user (spec10 §0)"
    )
    assert prs.covered_count == len(covered)


def test_score_ignores_who_wrote_the_test():
    """Same coverage via pre-existing vs quelltest-written tests ⇒ same score.

    spec10 non-negotiable #1: no metric may take quelltest's own output as its
    numerator.
    """
    by_existing = compute_prs([], covered_count=4)
    by_quelltest = compute_prs(
        [
            BucketedResult(
                requirement_id=f"r{i}",
                bucket=OutputBucket.WRITTEN,
                confidence_score=90,
            )
            for i in range(4)
        ],
        covered_count=0,
    )
    assert by_existing.score == by_quelltest.score == 100


# ── non-negotiable #4: zero findings is a good outcome ───────────────────────


def test_no_findings_is_not_a_failure():
    prs = compute_prs([], covered_count=0)
    assert prs.scored is False
    assert prs.tier == "gray"
    assert prs.tier_label == "No edge cases found"
    assert "Uncovered" not in prs.tier_label


# ── non-negotiable #2: never emit a number we cannot defend ──────────────────


def test_missing_test_suite_is_unscored_not_zero():
    results = [
        BucketedResult(requirement_id="r1", bucket=OutputBucket.FLAGGED),
    ]
    prs = compute_prs(results, coverage_known=False)
    assert prs.scored is False
    assert "Not scored" in prs.tier_label


@pytest.mark.parametrize(
    ("covered", "gaps", "expected"),
    [(0, 4, 0), (1, 3, 25), (2, 2, 50), (4, 0, 100)],
)
def test_score_is_ratio_of_covered_edge_cases(covered, gaps, expected):
    results = [
        BucketedResult(requirement_id=f"g{i}", bucket=OutputBucket.FLAGGED)
        for i in range(gaps)
    ]
    prs = compute_prs(results, covered_count=covered)
    assert prs.score == expected


# ── §4.3 coverage attribution ────────────────────────────────────────────────


def test_discovers_tests_in_nested_directories():
    """tests/integration/test_billing_api.py must be found (was invisible pre-spec10)."""
    checker = CoverageChecker(FIXTURE)
    assert checker.has_test_suite is True


def test_matches_by_call_expression_not_name_substring():
    """No test here is named *charge* or *refund*; matching must come from calls."""
    reqs = CodeGuardReader().read(FIXTURE / "src" / "billing.py")
    checked = CoverageChecker(FIXTURE).check(reqs)

    covering = {t for r in checked for t in r.covering_tests}
    assert covering, "call-expression matching must find the covering tests"
    assert not any("charge" in name or "refund" in name for name in covering), (
        "fixture is only meaningful if the test names do not contain the "
        "target function names"
    )


def test_no_test_suite_reports_unknown_not_covered(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def f(x):\n    if x <= 0:\n        raise ValueError('bad')\n    return x\n",
        encoding="utf-8",
    )
    checker = CoverageChecker(tmp_path)
    assert checker.has_test_suite is False
