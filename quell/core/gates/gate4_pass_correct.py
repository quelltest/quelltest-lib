"""Gate 4 — Test Passes on Correct Code.

Runs the generated test in an isolated subprocess against the *original* source.
The test MUST PASS for the candidate to continue.

Source files are never mutated here — gate 5 handles that.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from quell.core.gates.gate1_ast import GateContext
from quell.core.models import GateResult


def check(test_code: str, ctx: GateContext) -> GateResult:
    """Gate 4: generated test must pass on the original (correct) source."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_gate4_test.py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(test_code)
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tmp_path), "-x", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ctx.project_root or ".",
        )
        if result.returncode == 0:
            return GateResult(passed=True, gate=4)
        return GateResult(
            passed=False, gate=4,
            reason="test failed on correct code — likely false positive",
        )
    except subprocess.TimeoutExpired:
        return GateResult(passed=False, gate=4, reason="test timed out on correct code")
    finally:
        tmp_path.unlink(missing_ok=True)
