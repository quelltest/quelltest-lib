"""
Quell — Your code says what it should do. Quell proves it.

Quick start:
    from quell import Quell
    q = Quell()
    result = q.check("src/")
    print(f"Score: {result.score:.0%} | Gaps: {len(result.uncovered)}")
"""
__version__ = "1.0.0"
__author__ = "Shashank Bindal"

from quell.core.models import (
    BucketedResult,
    ConfidenceTier,
    ConstraintKind,
    FileScore,
    FlagReason,
    GateResult,
    GeneratedTest,
    OutputBucket,
    ProjectScore,
    QuellConfig,
    Requirement,
    SpecSource,
    VerificationResult,
    VerificationStatus,
    confidence_tier_for,
)
from quell.sdk import CheckResult, Quell

__all__ = [
    "Quell", "CheckResult",
    "Requirement", "ConstraintKind", "SpecSource",
    "GeneratedTest", "VerificationResult", "VerificationStatus",
    "QuellConfig", "ProjectScore", "FileScore",
    # v2.0.0
    "FlagReason", "GateResult", "ConfidenceTier", "OutputBucket",
    "BucketedResult", "confidence_tier_for",
]
