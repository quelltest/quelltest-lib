"""
Ablation harness: what does each rung of the §4.4 ladder actually contribute?
(spec10 §4.6, issue #153)

Why this shape, and not the one #153 specifies
----------------------------------------------
#153 asks for five arms -- baseline, trace-carved, mutation-first, CrossHair,
Hypothesis, MCP handoff. Four of those are unbuilt (#149, #150 are still open;
CrossHair and Hypothesis integrations do not exist). A harness that "compares"
strategies which are not implemented measures nothing and reports a table that
looks like evidence.

So this compares what actually shipped. Each rung of the strategy ladder is
turned off in turn, against the same project, and the yield is recorded:

    A0  none          pre-spec10 behaviour: literal stubs only
    A1  fixtures      + reuse the project's conftest fixtures        (#143)
    A2  + constructions  + mine real construction sites              (#144)
    A3  + guard_mocks    + guard-aware mocks                         (#145)

That answers the question a bake-off is for -- is each thing we built earning
its place? -- and it is runnable today rather than aspirational.

Yield is verified tests written, not tests generated. A generated test that
Gate 5 rejects is not a contribution.

    python benchmarks/ablation.py tests/fixtures/async_orm_project
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Cumulative arms: each adds one rung to the previous.
ARMS: list[tuple[str, frozenset[str]]] = [
    ("A0 literal stubs only", frozenset()),
    ("A1 + conftest fixtures", frozenset({"fixtures"})),
    ("A2 + mined constructions", frozenset({"fixtures", "constructions"})),
    ("A3 + guard-aware mocks", frozenset({"fixtures", "constructions", "guard_mocks"})),
]


@dataclass
class ArmResult:
    name: str
    gaps: int
    generated: int
    verified: int
    skipped: int
    seconds: float

    @property
    def yield_pct(self) -> float:
        return (self.verified / self.gaps * 100) if self.gaps else 0.0


def run_arm(project_root: Path, name: str, strategies: frozenset[str]) -> ArmResult:
    """Generate and verify every gap under one strategy configuration."""
    from quell.core.models import QuellConfig, VerificationStatus
    from quell.core.verifier import Verifier, verify_with_repair
    from quell.coverage.checker import CoverageChecker
    from quell.spec.code_guard_reader import CodeGuardReader
    from quell.synthesis.rule_engine import RuleEngine

    reader = CodeGuardReader()
    requirements: list = []
    for path in sorted(project_root.rglob("*.py")):
        # Compare the path RELATIVE to the project. Checking path.parts on the
        # absolute path filtered every source file when the project itself
        # lived under a directory called "tests" -- which is exactly where the
        # async_orm_project fixture lives, so the first run reported 0 gaps.
        try:
            rel = path.relative_to(project_root)
        except ValueError:
            continue
        if any(part in {".venv", "__pycache__", "tests"} for part in rel.parts):
            continue
        requirements.extend(reader.read(path))

    gaps = [r for r in CoverageChecker(project_root).check(requirements) if not r.is_covered]

    engine = RuleEngine(project_root=project_root, strategies=strategies)
    verifier = Verifier(QuellConfig(), project_root=project_root)

    generated = verified = skipped = 0
    start = time.time()
    for req in gaps:
        if not engine.can_handle(req):
            skipped += 1
            continue
        test = engine.generate(req)
        if test is None:
            skipped += 1
            continue
        generated += 1
        try:
            result = verify_with_repair(verifier, req, test)
        except Exception:  # noqa: BLE001 — one bad case must not end the run
            continue
        if result.status == VerificationStatus.VERIFIED:
            verified += 1

    return ArmResult(
        name=name,
        gaps=len(gaps),
        generated=generated,
        verified=verified,
        skipped=skipped,
        seconds=round(time.time() - start, 1),
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    project_root = Path(argv[1]).resolve()
    if not project_root.is_dir():
        print(f"not a directory: {project_root}")
        return 2

    print(f"Ablation on {project_root.name}\n")
    header = f"{'arm':<28}{'gaps':>6}{'gen':>6}{'verified':>10}{'yield':>8}{'sec':>7}"
    print(header)
    print("-" * len(header))

    results = []
    for name, strategies in ARMS:
        r = run_arm(project_root, name, strategies)
        results.append(r)
        print(
            f"{r.name:<28}{r.gaps:>6}{r.generated:>6}{r.verified:>10}"
            f"{r.yield_pct:>7.0f}%{r.seconds:>7}"
        )

    base = results[0].verified
    best = max(results, key=lambda r: r.verified)
    print()
    if best.verified > base:
        print(f"Best: {best.name}: {base} -> {best.verified} verified tests")
    else:
        print(f"No arm beat the baseline ({base} verified). The ladder is not earning its place here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
