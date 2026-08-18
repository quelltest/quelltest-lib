"""
Measured coverage: which test actually executed which line.
(spec10 §4.3, issue #142)

Why this exists
---------------
Every other coverage signal in Quell is an approximation of a runtime fact.
`checker.py` infers coverage from recursive test discovery plus import and
call-expression matching — better than the three hardcoded paths it replaced,
but still a guess. A test that reaches a guard through two layers of
indirection, a fixture, or a FastAPI TestClient is invisible to static
analysis, and a test that merely *mentions* a function is counted even if it
never runs the guarded branch.

Coverage is a runtime property. `pytest --cov --cov-context=test` records, per
line, which tests executed it. A requirement anchored at line L is covered iff
some test executed L. That is ground truth, and it makes the static heuristics
unnecessary rather than better.

Deliberately opt-in: running the suite is slow and can have side effects, so
nothing here executes unless the caller asks. On any failure — coverage not
installed, suite errors, no data file — this returns None, and the caller falls
back to static matching. Absence of measurement is never reported as absence of
coverage (spec10 non-negotiable #2).

Reference: CoverUp (arXiv 2403.16218) drives generation from coverage
measurements rather than inferring them.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Bound the suite run so a hanging or interactive test cannot wedge the CLI.
DEFAULT_TIMEOUT_S = 900


@dataclass
class CoverageMap:
    """Per-file, per-line set of test contexts that executed that line."""

    lines: dict[Path, dict[int, set[str]]] = field(default_factory=dict)

    def is_line_covered(self, file: Path, line: int) -> bool:
        try:
            resolved = file.resolve()
        except OSError:
            resolved = file
        return bool(self.lines.get(resolved, {}).get(line))

    def tests_for(self, file: Path, line: int) -> list[str]:
        try:
            resolved = file.resolve()
        except OSError:
            resolved = file
        return sorted(self.lines.get(resolved, {}).get(line, set()))

    @property
    def measured_files(self) -> int:
        return len(self.lines)


def measure(
    project_root: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> CoverageMap | None:
    """Run the project's suite under coverage contexts and read the result.

    Returns None — never an empty map — when measurement could not be
    performed, so the caller can distinguish "measured, nothing covered" from
    "could not measure". Those must not render the same way.
    """
    data_file = project_root / ".quell" / "coverage_contexts"
    try:
        data_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    if not _run_suite(project_root, data_file, timeout_s):
        return None
    return _read(data_file, project_root)


def _run_suite(project_root: Path, data_file: Path, timeout_s: int) -> bool:
    """Run pytest under coverage. True if a data file was produced.

    A non-zero exit is not treated as failure: a suite with failing tests still
    produces valid coverage data, and refusing to measure a red suite would
    make this useless exactly when a user most wants to know what is untested.
    """
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov", str(project_root),
        "--cov-context=test",
        "-q", "-p", "no:cacheprovider",
    ]
    env_data = {"COVERAGE_FILE": str(data_file)}
    try:
        import os

        env = {**os.environ, **env_data}
        subprocess.run(  # noqa: S603 — fixed argv, no shell
            cmd,
            cwd=str(project_root),
            capture_output=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return data_file.exists()


def _read(data_file: Path, project_root: Path) -> CoverageMap | None:
    """Read per-line contexts out of coverage's data file."""
    try:
        from coverage import CoverageData
    except ImportError:
        return None

    try:
        data = CoverageData(basename=str(data_file))
        data.read()
    except Exception:  # noqa: BLE001 — unreadable data is "could not measure"
        return None

    result = CoverageMap()
    try:
        for measured in data.measured_files():
            path = Path(measured)
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            per_line: dict[int, set[str]] = {}
            for line, contexts in (data.contexts_by_lineno(measured) or {}).items():
                # coverage records "" for lines executed outside any test
                # context (import time). Those are not evidence a test
                # exercised the line, so they are dropped.
                #
                # It also suffixes the pytest phase, e.g.
                #   tests/test_teams.py::test_happy_path|run
                # which would otherwise leak into user-facing covering_tests.
                named = {c.split("|", 1)[0] for c in contexts if c}
                named.discard("")
                if named:
                    per_line[int(line)] = named
            if per_line:
                result.lines[resolved] = per_line
    except Exception:  # noqa: BLE001
        return None

    return result if result.lines else None
