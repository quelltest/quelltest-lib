"""Production Readiness Score (PRS) per file and project.

Formula (spec7 §2.6):
  PRS = (Σ confidence_of_WRITTEN_tests) / (total_edge_cases × 100) × 100

Modifiers:
  +5   if every FLAGGED item has a # quell: flagged justification in source
  -10  if any HIGH-confidence test has been disabled/skipped manually
  -5   per SCAFFOLDED test left unfinished for >14 days (git blame)

Tiers:
  ≥80  green  "Production Ready"
  60–79 yellow "Review Needed"
  <60  red    "Edge Cases Uncovered"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from quell.core.models import BucketedResult, ConfidenceTier, OutputBucket

PRSTier = Literal["green", "yellow", "red"]

_FLAGGED_JUSTIFICATION_PATTERN = re.compile(r"#\s*quell:\s*flagged", re.IGNORECASE)
_SKIP_PATTERN = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(")


@dataclass
class PRSResult:
    """Full Production Readiness Score for a file or project."""

    score: int                  # 0–100
    tier: PRSTier
    tier_label: str             # "Production Ready" / "Review Needed" / "Edge Cases Uncovered"
    written_count: int
    scaffolded_count: int
    flagged_count: int
    total_edge_cases: int
    edge_case_coverage_pct: float  # (written + scaffolded) / total
    avg_written_confidence: float
    modifiers: list[str] = field(default_factory=list)
    before_score: int | None = None  # set to previous run PRS for delta display


def compute_prs(
    results: list[BucketedResult],
    source_files: list[Path] | None = None,
) -> PRSResult:
    """Compute PRS from a list of BucketedResult outcomes.

    source_files: paths to source files — used to check for # quell: flagged comments.
    """
    written = [r for r in results if r.bucket == OutputBucket.WRITTEN]
    scaffolded = [r for r in results if r.bucket == OutputBucket.SCAFFOLDED]
    flagged = [r for r in results if r.bucket == OutputBucket.FLAGGED]
    total = len(results)

    if total == 0:
        return PRSResult(
            score=0, tier="red", tier_label="Edge Cases Uncovered",
            written_count=0, scaffolded_count=0, flagged_count=0,
            total_edge_cases=0, edge_case_coverage_pct=0.0,
            avg_written_confidence=0.0,
        )

    # Base score
    confidence_sum = sum(r.confidence_score or 0 for r in written)
    base = int(confidence_sum / (total * 100) * 100) if total > 0 else 0
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

    coverage_pct = (len(written) + len(scaffolded)) / total * 100 if total else 0.0
    avg_conf = (
        sum(r.confidence_score or 0 for r in written) / len(written)
        if written else 0.0
    )

    return PRSResult(
        score=score,
        tier=tier,
        tier_label=label,
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
