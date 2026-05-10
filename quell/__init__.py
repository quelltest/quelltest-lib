"""
Quell — Your code says what it should do. Quell proves it.

Quick start:
    from quell import Quell
    q = Quell()
    result = q.check("src/")
    print(f"Score: {result.score:.0%} | Gaps: {len(result.uncovered)}")
"""
__version__ = "0.6.1"
__author__ = "Shashank Bindal"

from quell.core.models import (
    ConstraintKind,
    FileScore,
    GeneratedTest,
    ProjectScore,
    QuellConfig,
    Requirement,
    SpecSource,
    VerificationResult,
    VerificationStatus,
)
from quell.sdk import CheckResult, Quell

__all__ = [
    "Quell", "CheckResult",
    "Requirement", "ConstraintKind", "SpecSource",
    "GeneratedTest", "VerificationResult", "VerificationStatus",
    "QuellConfig", "ProjectScore", "FileScore",
]
