"""
Score threshold checking and exit code logic for `quell ci`.

Exit codes:
    0 = score meets threshold (or threshold is 0.0 = no check)
    1 = score is below threshold
"""
from __future__ import annotations
from dataclasses import dataclass

from quell.score.calculator import ProjectScore


@dataclass
class ThresholdResult:
    """Result of a threshold check."""

    passed: bool
    score: float       # actual score, 0.0 to 1.0
    threshold: float   # minimum required, 0.0 to 1.0
    message: str

    @property
    def exit_code(self) -> int:
        """0 if passed, 1 if failed."""
        return 0 if self.passed else 1


def check_threshold(score: ProjectScore, threshold: float) -> ThresholdResult:
    """
    Check whether the project mutation score meets the minimum threshold.

    A threshold of 0.0 always passes (no enforcement).

    Args:
        score: The current ProjectScore.
        threshold: Minimum required score as a fraction (e.g. 0.80 for 80%).

    Returns:
        ThresholdResult with passed/failed status and a human-readable message.
    """
    actual = score.total_score

    if threshold <= 0.0:
        return ThresholdResult(
            passed=True,
            score=actual,
            threshold=threshold,
            message=f"Score: {actual:.0%} (no threshold set)",
        )

    passed = actual >= threshold

    if passed:
        message = (
            f"Score {actual:.0%} meets threshold {threshold:.0%} ✓"
        )
    else:
        delta = threshold - actual
        message = (
            f"Score {actual:.0%} is below threshold {threshold:.0%} "
            f"(need {delta:.0%} more kills)"
        )

    return ThresholdResult(
        passed=passed,
        score=actual,
        threshold=threshold,
        message=message,
    )
