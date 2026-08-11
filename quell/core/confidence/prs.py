"""Production Readiness Score (PRS) per file and project.

Formula (spec10 §4.1 — REPLACES spec7 §2.6):
  PRS = (edge cases covered by ANY test) / (total edge cases) × 100

  covered = pre-existing tests (whoever wrote them) + tests quelltest just
            wrote and verified through all 5 gates

The spec7 formula was `(Σ confidence_of_WRITTEN_tests) / (total × 100) × 100`,
whose numerator counted only tests quelltest itself generated. Hand-written
tests contributed nothing, so any project quelltest could not auto-fix scored
0/100 permanently — including well-tested ones. That is a construct-validity
failure: the metric measured our own output while claiming to describe the
user's code. It cost us a user. See spec10 §0.

spec10 non-negotiables enforced here:
  #1 No metric may take quelltest's own output as its numerator.
  #2 Never emit a number we cannot defend — `scored=False` when coverage
     is unknown, and callers must print "not scored" rather than 0.
  #4 Zero findings is a GOOD outcome and never renders as failure.

Modifiers:
  +5   if every FLAGGED item has a # quell: flagged justification in source
  -10  if any HIGH-confidence test has been disabled/skipped manually

Tiers:
  ≥80  green  "Production Ready"
  60–79 yellow "Review Needed"
  <60  red    "Edge Cases Uncovered"
  n/a  gray   "Not scored" / "No edge cases found"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from quell.core.models import BucketedResult, ConfidenceTier, OutputBucket

PRSTier = Literal["green", "yellow", "red", "gray"]

_FLAGGED_JUSTIFICATION_PATTERN = re.compile(r"#\s*quell:\s*flagged", re.IGNORECASE)
_SKIP_PATTERN = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(")


@dataclass
class PRSResult:
    """Full Production Readiness Score for a file or project."""

    score: int                  # 0–100; meaningless unless `scored` is True
    tier: PRSTier
    tier_label: str             # "Production Ready" / "Review Needed" / "Edge Cases Uncovered"
    scored: bool = True         # False → callers MUST print "not scored", never 0
    covered_count: int = 0      # edge cases already covered by pre-existing tests
    written_count: int = 0
    scaffolded_count: int = 0
    flagged_count: int = 0
    total_edge_cases: int = 0
    edge_case_coverage_pct: float = 0.0  # (covered + written) / total
    avg_written_confidence: float = 0.0
    modifiers: list[str] = field(default_factory=list)
    before_score: int | None = None  # set to previous run PRS for delta display


def compute_prs(
    results: list[BucketedResult],
    source_files: list[Path] | None = None,
    covered_count: int = 0,
    coverage_known: bool = True,
) -> PRSResult:
    """Compute PRS from a list of BucketedResult outcomes.

    results:        outcomes for the *uncovered* edge cases (the gaps).
    source_files:   paths to source files — used to check for # quell: flagged comments.
    covered_count:  edge cases already covered by pre-existing tests, whoever
                    wrote them. This is what makes the score a property of the
                    codebase rather than of quelltest's own output (spec10 §4.1).
    coverage_known: False when no test suite could be discovered at all. The
                    result is then unscored — absence of evidence is not
                    evidence of absence (spec10 non-negotiable #2).
    """
    written = [r for r in results if r.bucket == OutputBucket.WRITTEN]
    scaffolded = [r for r in results if r.bucket == OutputBucket.SCAFFOLDED]
    flagged = [r for r in results if r.bucket == OutputBucket.FLAGGED]
    total = covered_count + len(results)

    # Zero findings is a GOOD outcome. Never render it as failure (#4).
    if total == 0:
        return PRSResult(
            score=0, tier="gray", tier_label="No edge cases found",
            scored=False,
        )

    # No discoverable test suite ⇒ we cannot tell covered from uncovered.
    # Report "not scored" rather than a 0 that reads as an accusation (#2).
    if not coverage_known:
        return PRSResult(
            score=0, tier="gray", tier_label="Not scored (no test suite found)",
            scored=False, total_edge_cases=total,
            written_count=len(written), scaffolded_count=len(scaffolded),
            flagged_count=len(flagged),
        )

    # Base score: what fraction of edge cases is tested by ANY test?
    # Pre-existing tests count identically to ones we wrote — the numerator
    # describes the codebase, never our own output (#1).
    tested = covered_count + len(written)
    base = int(tested / total * 100)
    base = max(0, min(100, base))

    modifiers: list[str] = []
    modifier_total = 0

    # +5 if every FLAGGED has justification in source
    if flagged and source_files:
        justified = _all_flagged_justified(flagged, source_files)
        if justified:
            modifier_total += 5
            modifiers.append("+5 (all flagged items documented with # quell: flagged)")

    # -10 if any HIGH test is skipped
    if written and source_files:
        has_skipped_high = _has_skipped_high_test(written, source_files)
        if has_skipped_high:
            modifier_total -= 10
            modifiers.append("-10 (a HIGH-confidence test is disabled/skipped)")

    score = max(0, min(100, base + modifier_total))
    tier, label = _tier(score)

    coverage_pct = tested / total * 100 if total else 0.0
    avg_conf = (
        sum(r.confidence_score or 0 for r in written) / len(written)
        if written else 0.0
    )

    return PRSResult(
        score=score,
        tier=tier,
        tier_label=label,
        scored=True,
        covered_count=covered_count,
        written_count=len(written),
        scaffolded_count=len(scaffolded),
        flagged_count=len(flagged),
        total_edge_cases=total,
        edge_case_coverage_pct=coverage_pct,
        avg_written_confidence=avg_conf,
        modifiers=modifiers,
    )


def _tier(score: int) -> tuple[PRSTier, str]:
    if score >= 80:
        return "green", "Production Ready"
    if score >= 60:
        return "yellow", "Review Needed"
    return "red", "Edge Cases Uncovered"


def _all_flagged_justified(
    flagged: list[BucketedResult],
    source_files: list[Path],
) -> bool:
    combined = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in source_files if p.exists()
    )
    return bool(_FLAGGED_JUSTIFICATION_PATTERN.search(combined))


def _has_skipped_high_test(
    written: list[BucketedResult],
    source_files: list[Path],
) -> bool:
    high_tests = [r for r in written if r.confidence_tier == ConfidenceTier.HIGH]
    if not high_tests:
        return False
    for p in source_files:
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8", errors="ignore")
        if _SKIP_PATTERN.search(content):
            return True
    return False
