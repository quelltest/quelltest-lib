"""
Privacy-safe diagnostic report for Quell runs.

Records WHERE Quell succeeded and WHERE it failed — without exposing any
source code, file contents, or full file paths. Safe to share with the
Quell maintainer to improve the rule engine.

Report location: .quell/report.json  (written after every --fix run)

What IS recorded:
  - Function names and constraint kinds
  - Verification outcome per requirement
  - Unknown type annotations the rule engine couldn't stub
  - Aggregate stats: written / failed / skipped counts

What is NOT recorded:
  - Source code
  - Full file paths (only basenames)
  - Function bodies
  - Any data that could identify proprietary business logic
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quell.core.models import (
    BucketedResult,
    FlagReason,
    OutputBucket,
    VerificationStatus,
)


@dataclass
class RequirementOutcome:
    """One requirement's result from a fix run."""
    constraint_kind: str
    function_name: str       # just the name, not source
    file_basename: str       # filename only, no path
    outcome: str             # written | fails_on_correct | doesnt_catch | timeout | error | skipped
    failure_reason: str | None = None
    unknown_types: list[str] = field(default_factory=list)
    error_snippet: str | None = None  # first 120 chars of error, no code


@dataclass
class QuellReport:
    quell_version: str
    generated_at: str
    target_name: str          # basename of scanned directory/file
    total_requirements: int
    already_covered: int
    written: int
    fails_on_correct: int
    doesnt_catch_violation: int
    timeout: int
    error: int
    skipped: int              # rule engine couldn't handle / no sig found
    outcomes: list[RequirementOutcome] = field(default_factory=list)

    @property
    def unknown_type_frequency(self) -> dict[str, int]:
        """Which custom types appeared most often — tells maintainer what stubs to add."""
        freq: dict[str, int] = {}
        for o in self.outcomes:
            for t in o.unknown_types:
                if t and not t.startswith("sig_not_found"):
                    freq[t] = freq.get(t, 0) + 1
        return dict(sorted(freq.items(), key=lambda x: -x[1]))

    @property
    def failure_reason_frequency(self) -> dict[str, int]:
        freq: dict[str, int] = {}
        for o in self.outcomes:
            if o.failure_reason:
                freq[o.failure_reason] = freq.get(o.failure_reason, 0) + 1
        return dict(sorted(freq.items(), key=lambda x: -x[1]))

    def to_dict(self) -> dict:  # type: ignore[type-arg]
        d = asdict(self)
        d["unknown_type_frequency"] = self.unknown_type_frequency
        d["failure_reason_frequency"] = self.failure_reason_frequency
        d["_note"] = (
            "This report contains no source code or full paths. "
            "Safe to share with the Quell maintainer to improve the rule engine."
        )
        return d


def write_report(report: QuellReport, project_root: Path) -> Path:
    """Write report to .quell/report.json and return the path."""
    out_dir = project_root / ".quell"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "report.json"
    out.write_text(json.dumps(report.to_dict(), indent=2))
    return out


def outcome_from_verification(
    constraint_kind: str,
    function_name: str,
    file_basename: str,
    status: VerificationStatus,
    unknown_types: list[str],
    error_message: str | None,
) -> RequirementOutcome:
    """Convert a VerificationResult into a RequirementOutcome."""
    outcome_map = {
        VerificationStatus.VERIFIED:               "written",
        VerificationStatus.FAILS_ON_CORRECT:       "fails_on_correct",
        VerificationStatus.DOESNT_CATCH_VIOLATION: "doesnt_catch_violation",
        VerificationStatus.TIMEOUT:                "timeout",
        VerificationStatus.SYNTAX_ERROR:           "syntax_error",
        VerificationStatus.ERROR:                  "error",
    }
    outcome = outcome_map.get(status, "error")

    # Failure reason: is it unknown types or something else?
    failure_reason = None
    if status == VerificationStatus.FAILS_ON_CORRECT:
        if unknown_types:
            failure_reason = "unknown_arg_types"
        else:
            failure_reason = "test_logic_incorrect"
    elif status == VerificationStatus.DOESNT_CATCH_VIOLATION:
        failure_reason = "test_too_weak"
    elif status == VerificationStatus.ERROR:
        failure_reason = "runtime_error"

    # Truncate error to first 120 chars — no source code leaks
    snippet = None
    if error_message:
        lines = [ln for ln in error_message.splitlines() if ln.strip()]
        snippet = lines[0][:120] if lines else error_message[:120]

    return RequirementOutcome(
        constraint_kind=constraint_kind,
        function_name=function_name,
        file_basename=file_basename,
        outcome=outcome,
        failure_reason=failure_reason,
        unknown_types=unknown_types,
        error_snippet=snippet,
    )


# ── v2.0.0: Three-bucket report ───────────────────────────────────────────────

@dataclass
class BucketedReport:
    """Three-bucket output report for quell find (spec7 §2.3 + §2.6)."""

    quell_version: str
    generated_at: str
    target_name: str
    total_edge_cases: int
    written_count: int
    scaffolded_count: int
    flagged_count: int
    prs_score: int              # 0–100
    prs_tier: str               # "green" | "yellow" | "red"
    prs_tier_label: str         # "Production Ready" | "Review Needed" | "Edge Cases Uncovered"
    avg_confidence: float       # average confidence of WRITTEN tests (0–100)
    edge_case_coverage_pct: float  # (written + scaffolded) / total * 100
    written: list[dict] = field(default_factory=list)    # [{req_id, file, confidence, tier}]
    scaffolded: list[dict] = field(default_factory=list) # [{req_id, file, reason}]
    flagged: list[dict] = field(default_factory=list)    # [{req_id, file, line, reason}]

    def to_dict(self) -> dict:  # type: ignore[type-arg]
        return asdict(self)


def bucketed_report_from_results(
    results: list[BucketedResult],
    quell_version: str,
    target_name: str,
    prs_score: int,
    prs_tier: str,
    prs_tier_label: str,
) -> BucketedReport:
    """Build a BucketedReport from a list of BucketedResult objects."""
    import datetime

    written = [r for r in results if r.bucket == OutputBucket.WRITTEN]
    scaffolded = [r for r in results if r.bucket == OutputBucket.SCAFFOLDED]
    flagged = [r for r in results if r.bucket == OutputBucket.FLAGGED]
    total = len(results)

    avg_conf = (
        sum(r.confidence_score or 0 for r in written) / len(written)
        if written else 0.0
    )
    coverage_pct = (len(written) + len(scaffolded)) / total * 100 if total else 0.0

    return BucketedReport(
        quell_version=quell_version,
        generated_at=datetime.datetime.utcnow().isoformat(),
        target_name=target_name,
        total_edge_cases=total,
        written_count=len(written),
        scaffolded_count=len(scaffolded),
        flagged_count=len(flagged),
        prs_score=prs_score,
        prs_tier=prs_tier,
        prs_tier_label=prs_tier_label,
        avg_confidence=avg_conf,
        edge_case_coverage_pct=coverage_pct,
        written=[
            {
                "requirement_id": r.requirement_id,
                "file": str(r.scaffold_file or r.source_file or ""),
                "confidence": r.confidence_score,
                "tier": r.confidence_tier.value if r.confidence_tier else None,
                "source_line": r.source_line,
            }
            for r in written
        ],
        scaffolded=[
            {
                "requirement_id": r.requirement_id,
                "scaffold_file": str(r.scaffold_file or ""),
                "source_file": str(r.source_file or ""),
                "source_line": r.source_line,
            }
            for r in scaffolded
        ],
        flagged=[
            {
                "requirement_id": r.requirement_id,
                "source_file": str(r.source_file or ""),
                "source_line": r.source_line,
                "reason": r.flag_reason.value if r.flag_reason else "unknown",
            }
            for r in flagged
        ],
    )


def write_bucketed_report(report: BucketedReport, project_root: Path) -> Path:
    """Write bucketed report to .quell/report.json and return the path."""
    out_dir = project_root / ".quell"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "report.json"
    out.write_text(json.dumps(report.to_dict(), indent=2))
    return out


def verification_status_to_bucket(
    status: VerificationStatus,
    unknown_types: list[str],
) -> tuple[OutputBucket, FlagReason | None]:
    """Map a VerificationStatus to an OutputBucket + optional FlagReason."""
    if status == VerificationStatus.VERIFIED:
        return OutputBucket.WRITTEN, None
    if status == VerificationStatus.SYNTAX_ERROR:
        return OutputBucket.FLAGGED, FlagReason.INVALID_SYNTAX
    if status == VerificationStatus.FAILS_ON_CORRECT:
        return OutputBucket.FLAGGED, FlagReason.GATE4_FAILURE
    if status == VerificationStatus.DOESNT_CATCH_VIOLATION:
        return OutputBucket.FLAGGED, FlagReason.GATE5_FAILURE
    # TIMEOUT or ERROR
    return OutputBucket.FLAGGED, FlagReason.GATE4_FAILURE
