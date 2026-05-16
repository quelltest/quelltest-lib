"""All domain models. Every pipeline stage uses these."""
from __future__ import annotations

import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SpecSource(StrEnum):
    DOCSTRING  = "docstring"
    TYPE       = "type"
    BUG_REPORT = "bug_report"
    MUTATION   = "mutation"
    PYSPARK    = "pyspark"
    CODE_GUARD = "code_guard"   # read from if/raise patterns in code


class ConstraintKind(StrEnum):
    """The kind of requirement extracted from any spec."""
    MUST_RAISE   = "must_raise"    # raises ExceptionType under condition
    MUST_RETURN  = "must_return"   # returns specific value/type
    BOUNDARY     = "boundary"      # value > / >= / < / <= threshold
    ENUM_VALID   = "enum_valid"    # value must be one of [X, Y, Z]
    ENUM_INVALID = "enum_invalid"  # invalid value must be rejected
    NOT_NONE     = "not_none"      # return must not be None
    NOT_NULL     = "not_null"      # PySpark column / variable must not be null
    TYPE_CHECK   = "type_check"    # type check guard (isinstance)
    AUTH_CHECK   = "auth_check"    # authentication/permission guard
    BARE_EXCEPT  = "bare_except"   # bare except: smell — catches everything
    SILENT_FAIL  = "silent_fail"   # returns None instead of raising
    MAGIC_VALUE  = "magic_value"   # hardcoded string/int in condition
    MUTATION     = "mutation"      # survived mutant
    BUG_REPRO    = "bug_repro"     # reproduce reported bug
    CUSTOM       = "custom"        # LLM handles free-form


class Requirement(BaseModel):
    """
    One testable requirement from any specification source.

    Examples:
      - from docstring "amount must be positive":
          ConstraintKind.BOUNDARY, target_function="process_payment"
      - from Pydantic Field(gt=0):
          ConstraintKind.BOUNDARY, target_function="PaymentRequest"
      - from bug "accepts zero amount silently":
          ConstraintKind.BUG_REPRO, target_function="process_payment"
    """
    id: str
    description: str
    constraint_kind: ConstraintKind
    source: SpecSource
    target_function: str
    target_file: Path
    violation_input: dict[str, Any] | None = None
    expected_behavior: str | None = None
    raw_spec_text: str | None = None
    source_line: int | None = None
    is_covered: bool = False
    covering_tests: list[str] = Field(default_factory=list)


class GeneratedTest(BaseModel):
    """A candidate test generated for a Requirement."""
    requirement_id: str
    test_function_name: str
    test_code: str
    test_file_path: Path
    explanation: str
    generated_by: str  # "rule_engine" | "llm:model-name"
    unknown_types: list[str] = Field(default_factory=list)  # types rule engine couldn't stub
    confidence_score: int | None = None  # 0-100; None means not yet scored

    def meets_confidence(self, threshold: int = 50) -> bool:
        """Return True if the confidence score meets or exceeds the threshold."""
        return self.confidence_score is None or self.confidence_score >= threshold


class VerificationStatus(StrEnum):
    VERIFIED               = "verified"
    FAILS_ON_CORRECT       = "fails_on_correct"
    DOESNT_CATCH_VIOLATION = "doesnt_catch_violation"
    SYNTAX_ERROR           = "syntax_error"
    TIMEOUT                = "timeout"
    ERROR                  = "error"


class VerificationResult(BaseModel):
    requirement_id: str
    generated_test: GeneratedTest
    status: VerificationStatus
    attempts: int = 1
    error_message: str | None = None
    duration_ms: int = 0


class FileScore(BaseModel):
    file_path: Path
    total_requirements: int
    covered_requirements: int
    quell_score: float  # 0.0–1.0

    @property
    def percentage(self) -> int:
        return int(self.quell_score * 100)

    @property
    def grade(self) -> str:
        if self.quell_score >= 0.80:
            return "A"
        if self.quell_score >= 0.60:
            return "B"
        if self.quell_score >= 0.40:
            return "C"
        return "F"


class ProjectScore(BaseModel):
    files: list[FileScore] = Field(default_factory=list)
    generated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow
    )

    @property
    def total_score(self) -> float:
        total = sum(f.total_requirements for f in self.files)
        if total == 0:
            return 0.0
        return sum(f.covered_requirements for f in self.files) / total

    @property
    def percentage(self) -> int:
        return int(self.total_score * 100)


class AuditEntry(BaseModel):
    timestamp: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow
    )
    requirement_id: str
    action: str
    file_path: Path | None = None
    test_function_name: str | None = None
    verification_status: VerificationStatus | None = None


class QuellConfig(BaseModel):
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5"
    ollama_base_url: str = "http://localhost:11434"
    max_verification_attempts: int = 3
    verification_timeout_seconds: int = 30
    auto_write: bool = False
    audit_log_path: Path = Path(".quell/audit.jsonl")
    backup_dir: Path = Path(".quell/backups")
    enable_docstring: bool = True
    enable_types: bool = True
    enable_mutations: bool = False  # off by default — mutmut not required
    enable_pyspark: bool = False    # off by default — pyspark optional dep
    score_threshold: float = 0.0
    diff_only: bool = False
    # v2.0.0 additions
    prs_threshold: int = 60         # minimum PRS to pass `quell ci`
    scaffold_dir: Path = Path("tests/scaffold")  # where SCAFFOLDED stubs go
    use_llm: bool = False           # opt-in LLM fallback (off by default)


# ── v2.0.0 models: confidence scoring and three-bucket output ─────────────────

class ConfidenceTier(StrEnum):
    """Confidence tier for a WRITTEN test (spec7 §2.5)."""
    HIGH   = "HIGH"    # ≥85 — ship without review
    MEDIUM = "MEDIUM"  # 60–84 — review recommended
    LOW    = "LOW"     # <60 — review required; gets # quell: review comment


class FlagReason(StrEnum):
    """Human-readable reason why a test was FLAGGED (not auto-written)."""
    EXTERNAL_API    = "depends on external API"
    ENV_VAR         = "depends on environment variable"
    OBJECT_STATE    = "depends on object state"
    LOCAL_VAR_GUARD = "local variable guard"
    ASYNC_FUNCTION  = "async function"
    INVALID_SYNTAX  = "generator produced invalid syntax"
    GATE4_FAILURE   = "test failed on correct code — likely false positive"
    GATE5_FAILURE   = "test passed even with bug injected — wouldn't catch it"
    SECURITY        = "generated test failed security review"
    DUPLICATE       = "duplicate of existing test"
    WEAK_ASSERTION  = "assertion too weak"
    TOO_SIMILAR     = "too similar to existing test"


class GateResult(BaseModel):
    """Result of a single gate check in the 5-gate pipeline."""
    passed: bool
    gate: int                      # 1–5
    reason: str | None = None      # set when passed=False


class OutputBucket(StrEnum):
    """Which bucket a candidate test lands in after the pipeline."""
    WRITTEN    = "WRITTEN"     # passed all 5 gates
    SCAFFOLDED = "SCAFFOLDED"  # passed gate 1+2; human assertion needed
    FLAGGED    = "FLAGGED"     # cannot auto-test; reason always provided


class BucketedResult(BaseModel):
    """Final outcome for one edge-case candidate after the full pipeline."""
    requirement_id: str
    bucket: OutputBucket
    flag_reason: FlagReason | None = None   # set when bucket == FLAGGED
    gates_passed: int = 0                   # 0–5
    generated_test: GeneratedTest | None = None
    confidence_score: int | None = None     # 0–100; set when bucket == WRITTEN
    confidence_tier: ConfidenceTier | None = None
    scaffold_file: Path | None = None       # set when bucket == SCAFFOLDED
    source_file: Path | None = None
    source_line: int | None = None


def confidence_tier_for(score: int) -> ConfidenceTier:
    """Map a 0–100 confidence score to its tier."""
    if score >= 85:
        return ConfidenceTier.HIGH
    if score >= 60:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW
