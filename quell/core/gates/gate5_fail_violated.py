"""Gate 5 — Test Fails on Violated Code.

Writes the violated source to a temp file, runs the test against it.
The test MUST FAIL — proving it actually catches the injected bug.

Source is always restored in a finally block (key invariant from CLAUDE.md).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from quell.core.gates.gate1_ast import GateContext
from quell.core.models import GateResult


def check(test_code: str, ctx: GateContext) -> GateResult:
    """Gate 5: generated test must fail when the violation is injected."""
    if not ctx.violated_source:
        # No violation available — can't run gate 5
        return GateResult(
            passed=False, gate=5,
            reason="no violation available for gate 5 check",
        )

    violated_path: Path | None = None
    test_path: Path | None = None

    try:
        # Write violated source to a temp file alongside original
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_violated.py", delete=False, encoding="utf-8"
        ) as vf:
            vf.write(ctx.violated_source)
            violated_path = Path(vf.name)

        # Write the test, patching the import to use violated file
        patched_test = _patch_imports(test_code, ctx.target_file, str(violated_path))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_gate5_test.py", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(patched_test)
            test_path = Path(tf.name)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-x", "-q", "--tb=no"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ctx.project_root or ".",
        )
        # Test FAILING (non-zero exit) means the gate PASSES
        if result.returncode != 0:
            return GateResult(passed=True, gate=5)
        return GateResult(
            passed=False, gate=5,
            reason="test passed even with bug injected — wouldn't catch it",
        )
    except subprocess.TimeoutExpired:
        return GateResult(passed=False, gate=5, reason="test timed out on violated code")
    finally:
        if violated_path:
            violated_path.unlink(missing_ok=True)
        if test_path:
            test_path.unlink(missing_ok=True)


def _patch_imports(test_code: str, original_file: str, violated_file: str) -> str:
    """Attempt to redirect the test's import of the original module to the violated copy.

    This is a best-effort heuristic — the verifier's existing violation injection
    approach (editing in-place with restore) remains the authoritative path.
    When in-place injection is used, ctx.violated_source is set to the modified
    file content and the original file is already on disk in its violated state,
    making this patch unnecessary.
    """
    # For now, return unchanged — the orchestrator in verifier.py handles the
    # file-on-disk approach via the existing _violate / finally-restore pattern.
    return test_code
