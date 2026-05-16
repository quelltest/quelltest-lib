"""Unit tests for confidence scoring and PRS (spec7 §2.5, §2.6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.confidence.badge import generate_badge
from quell.core.confidence.prs import PRSResult, compute_prs
from quell.core.confidence.score import ConfidenceContext, ConfidenceResult, compute_confidence
from quell.core.models import (
    BucketedResult,
    ConfidenceTier,
    FlagReason,
    GeneratedTest,
    OutputBucket,
    SpecSource,
    confidence_tier_for,
)


def _make_test(generated_by: str = "rule_engine", code: str = "") -> GeneratedTest:
    return GeneratedTest(
        requirement_id="req-1",
        test_function_name="test_x",
        test_code=code or "import pytest\ndef test_x():\n    pytest.raises(ValueError)\n",
        test_file_path=Path("tests/test_x.py"),
        explanation="test",
        generated_by=generated_by,
    )


def _make_written(confidence: int, tier: ConfidenceTier | None = None) -> BucketedResult:
    return BucketedResult(
        requirement_id="req-1",
        bucket=OutputBucket.WRITTEN,
        confidence_score=confidence,
        confidence_tier=tier or confidence_tier_for(confidence),
        gates_passed=5,
    )


def _make_flagged() -> BucketedResult:
    return BucketedResult(
        requirement_id="req-2",
        bucket=OutputBucket.FLAGGED,
        flag_reason=FlagReason.EXTERNAL_API,
    )


def _make_scaffolded() -> BucketedResult:
    return BucketedResult(
        requirement_id="req-3",
        bucket=OutputBucket.SCAFFOLDED,
        gates_passed=2,
    )


# ── ConfidenceScore ───────────────────────────────────────────────────────────

class TestComputeConfidence:
    def test_pydantic_source_yields_high_score(self):
        t = _make_test(code="import pytest\ndef test_x():\n    with pytest.raises(ValueError, match='positive'):\n        pass\n")
        ctx = ConfidenceContext(spec_source=SpecSource.TYPE, covering_test_count=0)
        result = compute_confidence(t, ctx)
        assert result.score >= 85
        assert result.tier == ConfidenceTier.HIGH

    def test_llm_generated_yields_lower_score(self):
        t = _make_test(generated_by="llm:groq-llama3")
        ctx = ConfidenceContext(spec_source=SpecSource.CODE_GUARD)
        result = compute_confidence(t, ctx)
        assert result.score < 70
        assert result.tier in (ConfidenceTier.MEDIUM, ConfidenceTier.LOW)

    def test_docstring_source_medium_range(self):
        t = _make_test(code="import pytest\ndef test_x():\n    pytest.raises(ValueError)\n")
        ctx = ConfidenceContext(spec_source=SpecSource.DOCSTRING, covering_test_count=0)
        result = compute_confidence(t, ctx)
        assert 55 <= result.score <= 100

    def test_covered_path_lowers_uniqueness(self):
        t = _make_test()
        ctx_unique = ConfidenceContext(spec_source=SpecSource.TYPE, covering_test_count=0)
        ctx_overlap = ConfidenceContext(spec_source=SpecSource.TYPE, covering_test_count=5)
        r_unique = compute_confidence(t, ctx_unique)
        r_overlap = compute_confidence(t, ctx_overlap)
        assert r_unique.score > r_overlap.score

    def test_strong_assertion_raises_score(self):
        strong_code = (
            "import pytest\ndef test_x(val):\n"
            "    with pytest.raises(ValueError, match='must be positive'):\n"
            "        fn(val)\n"
        )
        weak_code = "import pytest\ndef test_x(val):\n    pytest.raises(ValueError)\n"
        ctx = ConfidenceContext(spec_source=SpecSource.CODE_GUARD, covering_test_count=0)
        r_strong = compute_confidence(_make_test(code=strong_code), ctx)
        r_weak = compute_confidence(_make_test(code=weak_code), ctx)
        assert r_strong.score >= r_weak.score

    def test_score_clamped_0_100(self):
        t = _make_test()
        ctx = ConfidenceContext()
        result = compute_confidence(t, ctx)
        assert 0 <= result.score <= 100

    def test_result_has_all_factors(self):
        t = _make_test()
        ctx = ConfidenceContext(spec_source=SpecSource.TYPE)
        result = compute_confidence(t, ctx)
        assert "spec_source" in result.factors
        assert "violation" in result.factors
        assert "assertion" in result.factors
        assert "uniqueness" in result.factors


# ── PRS ───────────────────────────────────────────────────────────────────────

class TestComputePRS:
    def test_empty_results(self):
        prs = compute_prs([])
        assert prs.score == 0
        assert prs.tier == "red"

    def test_all_written_high_confidence(self):
        results = [_make_written(90)] * 5
        prs = compute_prs(results)
        assert prs.tier == "green"
        assert prs.score >= 80
        assert prs.written_count == 5
        assert prs.flagged_count == 0

    def test_all_flagged_gives_low_prs(self):
        results = [_make_flagged()] * 10
        prs = compute_prs(results)
        assert prs.score == 0
        assert prs.tier == "red"
        assert prs.flagged_count == 10

    def test_mixed_results(self):
        results = [_make_written(88)] * 3 + [_make_flagged()] * 2 + [_make_scaffolded()]
        prs = compute_prs(results)
        assert prs.written_count == 3
        assert prs.scaffolded_count == 1
        assert prs.flagged_count == 2
        assert 0 <= prs.score <= 100

    def test_edge_case_coverage_pct(self):
        results = [_make_written(85)] * 2 + [_make_scaffolded()] + [_make_flagged()] * 2
        prs = compute_prs(results)
        # 2 written + 1 scaffolded = 3 handled out of 5
        assert abs(prs.edge_case_coverage_pct - 60.0) < 0.01

    def test_tier_boundaries(self):
        high_results = [_make_written(95)] * 10
        low_results = [_make_flagged()] * 8 + [_make_written(95)] * 2
        prs_high = compute_prs(high_results)
        prs_low = compute_prs(low_results)
        assert prs_high.tier == "green"
        assert prs_low.tier in ("red", "yellow")

    def test_avg_confidence_computed(self):
        results = [_make_written(80), _make_written(90)]
        prs = compute_prs(results)
        assert abs(prs.avg_written_confidence - 85.0) < 0.01

    def test_tier_labels(self):
        from quell.core.confidence.prs import _tier
        assert _tier(80) == ("green", "Production Ready")
        assert _tier(65) == ("yellow", "Review Needed")
        assert _tier(40) == ("red", "Edge Cases Uncovered")


# ── Badge ─────────────────────────────────────────────────────────────────────

class TestGenerateBadge:
    def test_returns_svg_string(self):
        svg = generate_badge(84)
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    def test_score_in_badge(self):
        svg = generate_badge(84)
        assert "84%" in svg

    def test_green_for_high_score(self):
        svg = generate_badge(80)
        assert "#4c1" in svg

    def test_yellow_for_medium_score(self):
        svg = generate_badge(65)
        assert "#dfb317" in svg

    def test_red_for_low_score(self):
        svg = generate_badge(40)
        assert "#e05d44" in svg

    def test_score_clamped(self):
        svg_over = generate_badge(150)
        assert "100%" in svg_over
        svg_under = generate_badge(-10)
        assert "0%" in svg_under

    def test_explicit_tier_override(self):
        svg = generate_badge(50, tier="green")
        assert "#4c1" in svg

    def test_quell_prs_label(self):
        svg = generate_badge(75)
        assert "Quell PRS" in svg
