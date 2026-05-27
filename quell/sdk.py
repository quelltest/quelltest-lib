"""
Programmatic API. Use in CI scripts, MCP servers, other tools.

from quell import Quell
q = Quell()
q.check("src/")                     # find gaps
q.check("src/", fix=True)           # find + fix + write report
q.reproduce("zero amount accepted") # bug → test
q.prove("src/payments.py")          # coverage score
q.score()                           # project score
"""
from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from pathlib import Path

from quell.core.models import (
    ProjectScore,
    QuellConfig,
    Requirement,
    VerificationStatus,
)


@dataclass
class VerifyResult:
    """Result of quell.verify_test()."""
    verified: bool
    kills_mutants: int
    score_delta: float
    explanation: str
    status: str


@dataclass
class ScoreResult:
    """Result of quell.get_score()."""
    total: float
    percentage: int
    by_file: dict[str, float]
    total_mutants: int
    killed_mutants: int
    survived_mutants: int


@dataclass
class CheckResult:
    """Result of quell.check()."""
    requirements: list[Requirement]
    score: float
    report_path: Path | None = None  # set when fix=True

    @property
    def uncovered(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.is_covered]

    @property
    def covered(self) -> list[Requirement]:
        return [r for r in self.requirements if r.is_covered]


class Quell:
    """Main entry point for the Quell SDK."""

    def __init__(
        self,
        llm: str = "anthropic",
        model: str | None = None,
        project_root: str | Path = ".",
    ):
        self.config = QuellConfig(llm_provider=llm)
        if model:
            self.config = self.config.model_copy(update={"llm_model": model})
        self.root = Path(project_root).resolve()

    def check(
        self,
        target: str | Path,
        sources: list[str] | None = None,
        fix: bool = False,
    ) -> CheckResult:
        """Scan target for requirement gaps. fix=True generates + writes verified tests."""
        return asyncio.run(
            self._check(Path(target), sources or ["docstring", "type"], fix)
        )

    def reproduce(self, description: str, file: str | Path | None = None) -> bool:
        """Convert a bug description to a verified failing test. Returns True if written."""
        return asyncio.run(
            self._reproduce(description, Path(file) if file else None)
        )

    def prove(self, file: str | Path, function: str | None = None) -> float:
        """Return requirement coverage score (0.0–1.0) for a file/function."""
        result = self.check(file)
        reqs = (
            [r for r in result.requirements if r.target_function == function]
            if function else result.requirements
        )
        total = len(reqs)
        return sum(1 for r in reqs if r.is_covered) / total if total else 0.0

    def score(self) -> ProjectScore:
        """Calculate project-wide Quell Score."""
        from quell.score.calculator import calculate_score
        return calculate_score(self.root)

    def verify_test(self, test_code: str, source_file: str | Path) -> VerifyResult:
        """Verify that a test actually kills mutations in the source file."""
        from quell.core.verifier import Verifier
        from quell.core.models import GeneratedTest, VerificationStatus
        from quell.spec.code_guard_reader import CodeGuardReader
        from quell.spec.docstring_reader import DocstringReader
        from quell.spec.type_reader import TypeReader
        from quell.llm.client import LLMClient
        import re

        src_path = Path(source_file).resolve()
        
        # Extract all requirements for the file
        reqs = []
        reqs.extend(CodeGuardReader().read(src_path))
        try:
            llm = LLMClient.from_config(self.config)
            reqs.extend(DocstringReader(llm).read(src_path))
        except Exception:
            reqs.extend(DocstringReader(None).read(src_path))
        reqs.extend(TypeReader().read(src_path))
        
        if self.config.enable_pyspark:
            from quell.spec.pyspark_reader import PySparkReader
            reqs.extend(PySparkReader().read(src_path))

        # Find test function name
        test_func_match = re.search(r'def\s+(test_\w+)', test_code)
        if not test_func_match:
            return VerifyResult(
                verified=False,
                kills_mutants=0,
                score_delta=0.0,
                explanation="No test function (test_*) found in test code.",
                status="error",
            )
        test_func_name = test_func_match.group(1)
        
        # Filter requirements that match the function under test
        # Test function name might look like test_quell_myfunc_constraint or test_myfunc
        target_reqs = []
        for req in reqs:
            if req.target_function and (req.target_function in test_func_name):
                target_reqs.append(req)
        
        # Fallback: run against all requirements in this file if no function match
        if not target_reqs:
            target_reqs = reqs

        if not target_reqs:
            return VerifyResult(
                verified=False,
                kills_mutants=0,
                score_delta=0.0,
                explanation=f"No requirements found to verify in {src_path.name}.",
                status="doesnt_catch_violation",
            )

        verifier = Verifier(self.config, project_root=self.root)
        verified_count = 0
        last_status = VerificationStatus.DOESNT_CATCH_VIOLATION
        explanation_parts = []

        for req in target_reqs:
            candidate = GeneratedTest(
                requirement_id=req.id,
                test_function_name=test_func_name,
                test_code=test_code,
                test_file_path=src_path.parent / "temp_verify_test.py",
                explanation="Temporary verification test",
                generated_by="verify_test",
            )
            res = verifier.verify(req, candidate)
            if res.status == VerificationStatus.VERIFIED:
                verified_count += 1
                last_status = VerificationStatus.VERIFIED
            else:
                last_status = res.status
                if res.error_message:
                    explanation_parts.append(f"{req.id}: {res.error_message}")

        verified = verified_count > 0
        if verified:
            explanation = f"Test successfully verified! Kills {verified_count} mutant(s)."
            status_str = "verified"
        else:
            explanation = "Test failed verification. " + "; ".join(explanation_parts)
            status_str = last_status.value

        score_delta = (1.0 / len(reqs)) if (verified and reqs) else 0.0

        return VerifyResult(
            verified=verified,
            kills_mutants=verified_count,
            score_delta=score_delta,
            explanation=explanation,
            status=status_str,
        )

    def get_score(self, path: str | Path | None = None) -> ScoreResult:
        """Get current mutation score. Runs mutmut if needed."""
        from quell.score.calculator import calculate_score
        project_score = calculate_score(self.root)
        
        if path is not None:
            target_path = Path(path).resolve()
            found = None
            for f in project_score.files:
                if f.file_path.resolve() == target_path:
                    found = f
                    break
            if found:
                by_file = {str(found.file_path): found.quell_score}
                total_mutants = found.total_requirements
                killed_mutants = found.covered_requirements
                return ScoreResult(
                    total=found.quell_score,
                    percentage=found.percentage,
                    by_file=by_file,
                    total_mutants=total_mutants,
                    killed_mutants=killed_mutants,
                    survived_mutants=total_mutants - killed_mutants,
                )
            else:
                return ScoreResult(
                    total=0.0,
                    percentage=0,
                    by_file={},
                    total_mutants=0,
                    killed_mutants=0,
                    survived_mutants=0,
                )
        else:
            by_file = {str(f.file_path): f.quell_score for f in project_score.files}
            total_mutants = sum(f.total_requirements for f in project_score.files)
            killed_mutants = sum(f.covered_requirements for f in project_score.files)
            return ScoreResult(
                total=project_score.total_score,
                percentage=project_score.percentage,
                by_file=by_file,
                total_mutants=total_mutants,
                killed_mutants=killed_mutants,
                survived_mutants=total_mutants - killed_mutants,
            )

    # ── internals ─────────────────────────────────────────────────────────────

    async def _check(
        self, target: Path, sources: list[str], fix: bool
    ) -> CheckResult:
        from quell.coverage.checker import CoverageChecker
        from quell.llm.client import LLMClient
        from quell.spec.docstring_reader import DocstringReader
        from quell.spec.type_reader import TypeReader

        llm = LLMClient.from_config(self.config)

        files = (
            [
                f for f in target.rglob("*.py")
                if "test" not in f.name
                and ".venv" not in str(f)
                and "site-packages" not in str(f)
                and "__pycache__" not in str(f)
            ]
            if target.is_dir() else [target]
        )

        reqs: list[Requirement] = []
        for f in files:
            if "docstring" in sources:
                reqs.extend(DocstringReader(llm).read(f))
            if "type" in sources:
                reqs.extend(TypeReader().read(f))
            if self.config.enable_pyspark:
                from quell.spec.pyspark_reader import PySparkReader
                reqs.extend(PySparkReader().read(f))

        reqs = CoverageChecker(self.root).check(reqs)

        report_path: Path | None = None

        if fix:
            report_path = self._fix_gaps(reqs, target)

        total = len(reqs)
        covered = sum(1 for r in reqs if r.is_covered)
        return CheckResult(
            requirements=reqs,
            score=covered / total if total else 0.0,
            report_path=report_path,
        )

    def _fix_gaps(self, reqs: list[Requirement], target: Path) -> Path:
        """Run rule engine → verifier → writer for each uncovered requirement.
        Returns the path to the written diagnostic report.
        """
        import quell
        from quell.core.verifier import Verifier
        from quell.core.writer import Writer
        from quell.report.generator import (
            QuellReport,
            RequirementOutcome,
            outcome_from_verification,
            write_report,
        )
        from quell.synthesis.rule_engine import RuleEngine

        engine = RuleEngine()
        verifier = Verifier(self.config, project_root=self.root)
        writer = Writer(self.config)

        outcomes: list[RequirementOutcome] = []
        written = fails_on_correct = doesnt_catch = timeout = error = skipped = 0
        already_covered = sum(1 for r in reqs if r.is_covered)

        for req in reqs:
            if req.is_covered:
                continue

            if not engine.can_handle(req):
                skipped += 1
                outcomes.append(RequirementOutcome(
                    constraint_kind=req.constraint_kind.value,
                    function_name=req.target_function,
                    file_basename=req.target_file.name,
                    outcome="skipped",
                    failure_reason="unsupported_constraint_kind",
                ))
                continue

            test = engine.generate(req)
            if test is None:
                skipped += 1
                continue

            result = verifier.verify(req, test)

            outcomes.append(outcome_from_verification(
                constraint_kind=req.constraint_kind.value,
                function_name=req.target_function,
                file_basename=req.target_file.name,
                status=result.status,
                unknown_types=test.unknown_types,
                error_message=result.error_message,
            ))

            if result.status == VerificationStatus.VERIFIED:
                writer.write(test, req.id)
                req.is_covered = True
                written += 1
            elif result.status == VerificationStatus.FAILS_ON_CORRECT:
                fails_on_correct += 1
            elif result.status == VerificationStatus.DOESNT_CATCH_VIOLATION:
                doesnt_catch += 1
            elif result.status == VerificationStatus.TIMEOUT:
                timeout += 1
            else:
                error += 1

        report = QuellReport(
            quell_version=getattr(quell, "__version__", "0.4.0"),
            generated_at=datetime.datetime.utcnow().isoformat(),
            target_name=target.name,
            total_requirements=len(reqs),
            already_covered=already_covered,
            written=written,
            fails_on_correct=fails_on_correct,
            doesnt_catch_violation=doesnt_catch,
            timeout=timeout,
            error=error,
            skipped=skipped,
            outcomes=outcomes,
        )
        return write_report(report, self.root)

    async def _reproduce(
        self, description: str, target_file: Path | None
    ) -> bool:
        from quell.core.verifier import Verifier
        from quell.core.writer import Writer
        from quell.llm.client import LLMClient
        from quell.spec.bug_reader import BugReader
        from quell.synthesis.llm_engine import LLMSynthesizer

        llm = LLMClient.from_config(self.config)
        reqs = BugReader(llm, self.root).read_from_description(
            description, target_file
        )
        if not reqs:
            return False
        req = reqs[0]
        test = await LLMSynthesizer(llm, self.config).synthesize(req)
        result = Verifier(self.config, project_root=self.root).verify(req, test)
        if result.status == VerificationStatus.VERIFIED:
            Writer(self.config).write(test, req.id)
            return True
        return False
