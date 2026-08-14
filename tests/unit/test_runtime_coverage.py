"""spec10 §4.3 / issue #142 — measured coverage as ground truth.

Static inference cannot see a test that reaches a guard through a fixture, two
layers of indirection, or a TestClient — and it counts a test that merely
*mentions* a function even if it never runs the guarded branch. Executed-line
data settles both cases.

The distinction these tests protect: "measured, nothing ran it" (a real gap)
must not be confused with "could not measure" (unknown). Reporting the second
as the first is exactly the class of false claim spec10 non-negotiable #2
forbids.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.models import ConstraintKind, Requirement, SpecSource
from quell.coverage.checker import CoverageChecker
from quell.coverage.runtime import CoverageMap


def _req(src: Path, line: int) -> Requirement:
    return Requirement(
        id=f"r{line}",
        source=SpecSource.CODE_GUARD,
        description="guard",
        constraint_kind=ConstraintKind.NOT_NULL,
        target_function="handle",
        target_file=src,
        source_line=line,
    )


@pytest.fixture
def src(tmp_path: Path) -> Path:
    f = tmp_path / "svc.py"
    f.write_text(
        "def handle(x):\n"
        "    if not x:\n"
        "        raise ValueError('x')\n"
        "    return x\n",
        encoding="utf-8",
    )
    return f


# ── CoverageMap ──────────────────────────────────────────────────────────────


def test_reports_covered_and_uncovered_lines(src: Path):
    cmap = CoverageMap(lines={src.resolve(): {2: {"tests/test_a.py::test_guard"}}})
    assert cmap.is_line_covered(src, 2) is True
    assert cmap.is_line_covered(src, 3) is False
    assert cmap.tests_for(src, 2) == ["tests/test_a.py::test_guard"]
    assert cmap.tests_for(src, 3) == []


def test_unknown_file_is_not_covered(tmp_path: Path):
    cmap = CoverageMap(lines={})
    assert cmap.is_line_covered(tmp_path / "nope.py", 1) is False


# ── checker integration ──────────────────────────────────────────────────────


def test_measured_coverage_overrides_static_inference(src: Path, tmp_path: Path):
    """A line executed by a test counts, even with no static evidence at all."""
    checker = CoverageChecker(tmp_path)
    checker.use_runtime_coverage(
        CoverageMap(lines={src.resolve(): {2: {"tests/test_x.py::test_indirect"}}})
    )
    [req] = checker.check([_req(src, 2)])

    assert req.is_covered is True
    assert req.covering_tests == ["tests/test_x.py::test_indirect"]
    assert checker.mode == "measured"


def test_measured_but_unexecuted_is_a_real_gap(src: Path, tmp_path: Path):
    """Measured-and-empty must NOT silently fall back to inference."""
    checker = CoverageChecker(tmp_path)
    checker.use_runtime_coverage(
        CoverageMap(lines={src.resolve(): {4: {"tests/test_x.py::test_other"}}})
    )
    [req] = checker.check([_req(src, 2)])

    assert req.is_covered is False
    assert req.covering_tests == []


def test_mode_is_inferred_without_measurement(tmp_path: Path):
    checker = CoverageChecker(tmp_path)
    assert checker.mode == "inferred"
    checker.use_runtime_coverage(CoverageMap(lines={Path("x"): {1: {"t"}}}))
    assert checker.mode == "measured"
    checker.use_runtime_coverage(None)
    assert checker.mode == "inferred"


def test_requirement_without_a_line_falls_back(src: Path, tmp_path: Path):
    """No anchor line ⇒ nothing to look up ⇒ static path, not a false gap."""
    checker = CoverageChecker(tmp_path)
    checker.use_runtime_coverage(CoverageMap(lines={src.resolve(): {2: {"t"}}}))

    req = _req(src, 2)
    req.source_line = None
    [checked] = checker.check([req])
    assert checked.is_covered is False  # inferred: no test file exists here


def test_broken_coverage_map_falls_back_rather_than_raising(src: Path, tmp_path: Path):
    """invariant #6 — a bad map degrades to inference, never an exception."""

    class Broken:
        def is_line_covered(self, *_a, **_k):
            raise RuntimeError("corrupt")

    checker = CoverageChecker(tmp_path)
    checker.use_runtime_coverage(Broken())
    [req] = checker.check([_req(src, 2)])
    assert req.is_covered is False


# ── measure() failure modes ──────────────────────────────────────────────────


def test_measure_returns_none_when_suite_cannot_run(tmp_path: Path):
    """None, never an empty map: 'could not measure' != 'nothing covered'."""
    from quell.coverage import runtime

    assert runtime.measure(tmp_path, timeout_s=30) is None
