"""Per-test confidence scoring — 4 weighted factors, 0–100 result.

Factors (spec7 §2.5):
  Spec source quality    35%  — how reliable the spec source is
  Violation specificity  25%  — how targeted the violation injection is
  Assertion strength     25%  — how specific the pytest assertion is
  Coverage uniqueness    15%  — whether this test covers a path nothing else covers
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from quell.core.models import ConfidenceTier, GeneratedTest, SpecSource, confidence_tier_for

# ── Factor weights (must sum to 100) ─────────────────────────────────────────
_W_SPEC_SOURCE = 35
_W_VIOLATION   = 25
_W_ASSERTION   = 25
_W_UNIQUENESS  = 15

# ── Spec source base scores ───────────────────────────────────────────────────
_SPEC_SOURCE_SCORES: dict[str, int] = {
    SpecSource.TYPE:       95,   # Pydantic Field constraint
    SpecSource.DOCSTRING:  88,   # docstring "Raises:" block
    SpecSource.CODE_GUARD: 80,   # if/raise pattern
    SpecSource.PYSPARK:    80,   # PySpark StructType schema
    SpecSource.MUTATION:   70,   # survived mutant
    SpecSource.BUG_REPORT: 55,   # natural-language bug description (LLM)
}

_LLM_GENERATED_SCORE = 55  # fallback when generated_by starts with "llm"

# ── Violation specificity: inferred from generated_by and test code ───────────
_VIOLATION_PATTERNS = [
    (r"literal.*bound|boundary|gt|lt|ge|le", 95),   # literal bound flip
    (r"raises.*Error|exception", 85),                # exception class swap
    (r"semantic|mutation|mutant", 70),               # semantic mutation
]

# ── Assertion strength patterns ───────────────────────────────────────────────
_ASSERTION_STRONG   = re.compile(r"pytest\.raises\(.*,\s*match=")   # exc + message
_ASSERTION_SPECIFIC = re.compile(r"pytest\.raises\(")               # specific exception
_ASSERTION_VALUE    = re.compile(r"assert\s+\w+\s*[=!<>]=")         # value comparison

GeneratedBy = Literal["rule_engine", "llm"] | str


@dataclass
class ConfidenceContext:
    """Extra context for scoring beyond the GeneratedTest itself."""

    spec_source: SpecSource = SpecSource.CODE_GUARD
    covering_test_count: int = 0  # how many other tests cover the same path
    violation_description: str = ""  # description of the injection used


@dataclass
class ConfidenceResult:
    """Full confidence scoring breakdown."""

    score: int
    tier: ConfidenceTier
    spec_source_score: int
    violation_score: int
    assertion_score: int
    uniqueness_score: int
    factors: dict[str, int] = field(default_factory=dict)


def compute_confidence(test: GeneratedTest, ctx: ConfidenceContext) -> ConfidenceResult:
    """Compute 0–100 confidence for a generated test."""
    spec = _score_spec_source(test, ctx)
    viol = _score_violation(test, ctx)
    assr = _score_assertion(test)
    uniq = _score_uniqueness(ctx)

    raw = (
        spec * _W_SPEC_SOURCE
        + viol * _W_VIOLATION
        + assr * _W_ASSERTION
        + uniq * _W_UNIQUENESS
    ) // 100

    score = max(0, min(100, raw))

    return ConfidenceResult(
        score=score,
        tier=confidence_tier_for(score),
        spec_source_score=spec,
        violation_score=viol,
        assertion_score=assr,
        uniqueness_score=uniq,
        factors={
            "spec_source": spec,
            "violation": viol,
            "assertion": assr,
            "uniqueness": uniq,
        },
    )


def _score_spec_source(test: GeneratedTest, ctx: ConfidenceContext) -> int:
    if test.generated_by.startswith("llm"):
        return _LLM_GENERATED_SCORE
    return _SPEC_SOURCE_SCORES.get(ctx.spec_source, 70)


def _score_violation(test: GeneratedTest, ctx: ConfidenceContext) -> int:
    if test.generated_by.startswith("llm"):
        return 50  # LLM-suggested mutation
    desc = ctx.violation_description.lower()
    for pattern, score in _VIOLATION_PATTERNS:
        if re.search(pattern, desc):
            return score
    return 70  # default: semantic mutation


def _score_assertion(test: GeneratedTest) -> int:
    code = test.test_code
    if _ASSERTION_STRONG.search(code):
        return 95
    if _ASSERTION_SPECIFIC.search(code):
        return 85
    if _ASSERTION_VALUE.search(code):
        return 80
    # Generic pytest.raises or no assertion
    if "pytest.raises" in code:
        return 70
    return 60


def _score_uniqueness(ctx: ConfidenceContext) -> int:
    if ctx.covering_test_count == 0:
        return 90   # covers a path no other test covers
    if ctx.covering_test_count == 1:
        return 70   # partial overlap
    return 40       # full overlap — another test covers this path
