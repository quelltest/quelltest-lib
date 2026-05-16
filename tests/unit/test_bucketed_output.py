"""Unit tests for three-bucket output and PRS calculation (spec7 §2.3, §2.6).

Closes #65.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.confidence.prs import compute_prs
from quell.core.models import (
    BucketedResult,
    ConfidenceTier,
    FlagReason,
    OutputBucket,
    VerificationStatus,
)
from quell.report.generator import (
    BucketedReport,
    bucketed_report_from_results,
    verification_status_to_bucket,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _written(req_id: str, confidence: int = 80) -> BucketedResult:
    tier = ConfidenceTier.HIGH if confidence >= 85 else ConfidenceTier.MEDIUM
    return BucketedResult(
        requirement_id=req_id,
        bucket=OutputBucket.WRITTEN,
        gates_passed=5,
        confidence_score=confidence,
        confidence_tier=tier,
    )


def _scaffolded(req_id: str) -> BucketedResult:
    return BucketedResult(
        requirement_id=req_id,
        bucket=OutputBucket.SCAFFOLDED,
        gates_passed=3,
    )


def _flagged(req_id: str, reason: FlagReason = FlagReason.EXTERNAL_API) -> BucketedResult:
    return BucketedResult(
        requirement_id=req_id,
        bucket=OutputBucket.FLAGGED,
        flag_reason=reason,
        gates_passed=0,
    )


# ── PRS: all-WRITTEN ──────────────────────────────────────────────────────────


class TestPRSAllWritten:
    def test_high_prs_when_all_written(self) -> None:
        results = [_written("r1", 90), _written("r2", 85), _written("r3", 95)]
        prs = compute_prs(results)
        assert prs.written_count == 3
        assert prs.scaffolded_count == 0
        assert prs.flagged_count == 0
        assert prs.score >= 80
        assert prs.tier == "green"

    def test_coverage_100_pct_all_written(self) -> None:
        results = [_written("r1"), _written("r2")]
        prs = compute_prs(results)
        assert prs.edge_case_coverage_pct == 100.0

    def test_green_tier_label(self) -> None:
        results = [_written("r1", 90)]
        prs = compute_prs(results)
        assert prs.tier_label == "Production Ready"


# ── PRS: mixed buckets ────────────────────────────────────────────────────────


class TestPRSMixed:
    def test_counts_correct_for_mixed(self) -> None:
        results = [
            _written("r1"), _written("r2"),
            _scaffolded("r3"), _scaffolded("r4"), _scaffolded("r5"),
            _flagged("r6"),
        ]
        prs = compute_prs(results)
        assert prs.written_count == 2
        assert prs.scaffolded_count == 3
        assert prs.flagged_count == 1
        assert prs.total_edge_cases == 6

    def test_coverage_pct_includes_scaffolded(self) -> None:
        results = [_written("r1"), _scaffolded("r2"), _flagged("r3")]
        prs = compute_prs(results)
        # (1 written + 1 scaffolded) / 3 total = 66.67%
        assert abs(prs.edge_case_coverage_pct - 66.67) < 0.1

    def test_avg_confidence_only_counts_written(self) -> None:
        results = [_written("r1", 80), _written("r2", 60), _scaffolded("r3"), _flagged("r4")]
        prs = compute_prs(results)
        assert abs(prs.avg_written_confidence - 70.0) < 0.01

    def test_low_confidence_written_gives_yellow_or_red(self) -> None:
        results = [_written("r1", 40), _flagged("r2"), _flagged("r3")]
        prs = compute_prs(results)
        assert prs.tier in ("yellow", "red")


# ── PRS: empty results ────────────────────────────────────────────────────────


class TestPRSEmpty:
    def test_empty_results_returns_zero(self) -> None:
        prs = compute_prs([])
        assert prs.score == 0
        assert prs.tier == "red"
        assert prs.total_edge_cases == 0


# ── PRS: +5 modifier (flagged items documented) ───────────────────────────────


class TestPRSFlaggedJustification:
    def test_plus5_when_flagged_documented(self, tmp_path: Path) -> None:
        src = tmp_path / "source.py"
        src.write_text("def foo(): pass  # quell: flagged\n")
        results = [_written("r1", 60), _flagged("r2")]
        prs_without = compute_prs(results)
        prs_with = compute_prs(results, source_files=[src])
        assert prs_with.score == prs_without.score + 5
        assert any("+5" in m for m in prs_with.modifiers)

    def test_no_modifier_when_flagged_not_documented(self, tmp_path: Path) -> None:
        src = tmp_path / "source.py"
        src.write_text("def foo(): pass\n")
        results = [_written("r1", 60), _flagged("r2")]
        prs = compute_prs(results, source_files=[src])
        assert not any("+5" in m for m in prs.modifiers)


# ── PRS: -10 modifier (HIGH test skipped) ────────────────────────────────────


class TestPRSSkippedHighTest:
    def test_minus10_when_high_test_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "tests.py"
        src.write_text("@pytest.mark.skip\ndef test_foo(): pass\n")
        results = [_written("r1", 90)]  # HIGH confidence
        prs_without = compute_prs(results)
        prs_with = compute_prs(results, source_files=[src])
        assert prs_with.score == max(0, prs_without.score - 10)
        assert any("-10" in m for m in prs_with.modifiers)

    def test_no_penalty_when_medium_test_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "tests.py"
        src.write_text("@pytest.mark.skip\ndef test_foo(): pass\n")
        results = [_written("r1", 70)]  # MEDIUM confidence
        prs = compute_prs(results, source_files=[src])
        # No -10 because no HIGH test was skipped
        assert not any("-10" in m for m in prs.modifiers)


# ── PRS tiers ─────────────────────────────────────────────────────────────────


class TestPRSTiers:
    @pytest.mark.parametrize("score,expected_tier,expected_label", [
        (80, "green", "Production Ready"),
        (95, "green", "Production Ready"),
        (60, "yellow", "Review Needed"),
        (79, "yellow", "Review Needed"),
        (0, "red", "Edge Cases Uncovered"),
        (59, "red", "Edge Cases Uncovered"),
    ])
    def test_tier_thresholds(
        self, score: int, expected_tier: str, expected_label: str
    ) -> None:
        from quell.core.confidence.prs import _tier
        tier, label = _tier(score)
        assert tier == expected_tier
        assert label == expected_label


# ── BucketedReport ────────────────────────────────────────────────────────────


class TestBucketedReport:
    def _make_report(self) -> BucketedReport:
        results = [_written("r1", 85), _scaffolded("r2"), _flagged("r3")]
        return bucketed_report_from_results(
            results=results,
            quell_version="2.0.0",
            target_name="payments.py",
            prs_score=72,
            prs_tier="yellow",
            prs_tier_label="Review Needed",
        )

    def test_counts_in_report(self) -> None:
        report = self._make_report()
        assert report.written_count == 1
        assert report.scaffolded_count == 1
        assert report.flagged_count == 1
        assert report.total_edge_cases == 3

    def test_prs_fields_preserved(self) -> None:
        report = self._make_report()
        assert report.prs_score == 72
        assert report.prs_tier == "yellow"
        assert report.prs_tier_label == "Review Needed"

    def test_to_dict_serializable(self) -> None:
        import json
        report = self._make_report()
        d = report.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise

    def test_avg_confidence_only_from_written(self) -> None:
        report = self._make_report()
        assert abs(report.avg_confidence - 85.0) < 0.01

    def test_coverage_pct(self) -> None:
        report = self._make_report()
        # (1 written + 1 scaffolded) / 3 = 66.67%
        assert abs(report.edge_case_coverage_pct - 66.67) < 0.1


# ── verification_status_to_bucket ────────────────────────────────────────────


class TestVerificationStatusToBucket:
    def test_verified_maps_to_written(self) -> None:
        bucket, reason = verification_status_to_bucket(VerificationStatus.VERIFIED, [])
        assert bucket == OutputBucket.WRITTEN
        assert reason is None

    def test_syntax_error_maps_to_flagged(self) -> None:
        bucket, reason = verification_status_to_bucket(VerificationStatus.SYNTAX_ERROR, [])
        assert bucket == OutputBucket.FLAGGED
        assert reason == FlagReason.INVALID_SYNTAX

    def test_fails_on_correct_maps_to_flagged(self) -> None:
        bucket, reason = verification_status_to_bucket(VerificationStatus.FAILS_ON_CORRECT, [])
        assert bucket == OutputBucket.FLAGGED
        assert reason == FlagReason.GATE4_FAILURE

    def test_doesnt_catch_maps_to_flagged(self) -> None:
        bucket, reason = verification_status_to_bucket(
            VerificationStatus.DOESNT_CATCH_VIOLATION, []
        )
        assert bucket == OutputBucket.FLAGGED
        assert reason == FlagReason.GATE5_FAILURE

    def test_timeout_maps_to_flagged(self) -> None:
        bucket, reason = verification_status_to_bucket(VerificationStatus.TIMEOUT, [])
        assert bucket == OutputBucket.FLAGGED
        assert reason is not None
