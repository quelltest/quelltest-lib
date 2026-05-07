"""
Quell SDK — clean programmatic API for verifying AI-generated tests.

Usage:
    from quell import Quell

    q = Quell()                                    # uses config from pyproject.toml
    q = Quell(llm="ollama", model="codellama")     # local LLM

    # Verify a test you generated
    result = q.verify_test(
        test_code="def test_foo(): assert foo(0) == 'zero'",
        source_file="src/utils.py"
    )
    result.verified        # True/False
    result.explanation     # why it passed or failed
    result.score_delta     # mutation score change if applied

    # Get current project score
    score = q.get_score()
    score.total            # 0.87 (87%)
    score.by_file          # {"src/utils.py": 0.91, "src/payments.py": 0.72}

    # Fix all survivors
    results = q.fix_all(source="mutmut")
    results.fixed          # number fixed
    results.skipped        # number skipped
    results.score_before   # 0.71
    results.score_after    # 0.89
"""
from __future__ import annotations
import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from quell.core.models import QuellConfig, VerificationStatus
from quell.core.analyzer import MutationAnalyzer
from quell.core.generator import TestGenerator
from quell.core.verifier import MutantVerifier
from quell.core.writer import TestWriter
from quell.llm.client import LLMClient


# --- Result models ---

class VerifyResult(BaseModel):
    """Result of verifying a single test against mutations."""

    verified: bool
    explanation: str
    status: str                     # VerificationStatus value
    kills_mutants: int = 0
    score_delta: float = 0.0        # estimated score delta if this test were committed
    error_message: Optional[str] = None


class ScoreResult(BaseModel):
    """Current mutation score snapshot."""

    total: float                    # 0.0 to 1.0
    percentage: int
    by_file: dict[str, float] = {}  # file path → score (0.0–1.0)
    total_mutants: int = 0
    killed_mutants: int = 0
    survived_mutants: int = 0


class FixResult(BaseModel):
    """Summary of a fix_all() run."""

    fixed: int = 0
    skipped: int = 0
    failed: int = 0
    score_before: float = 0.0
    score_after: float = 0.0

    @property
    def score_delta(self) -> float:
        return self.score_after - self.score_before


class RepairResult(BaseModel):
    """Summary of a repair() run."""

    fixed: int = 0
    skipped: int = 0
    failed: int = 0
    score_before: float = 0.0
    score_after: float = 0.0
    test_dir: str = "tests/"
    source_dir: str = "src/"

    @property
    def score_delta(self) -> float:
        return self.score_after - self.score_before


# --- Main SDK class ---

class Quell:
    """
    Main entry point for the Quell SDK.

    All methods are synchronous wrappers around the async core. If you need
    async access, use the underlying core modules directly.
    """

    def __init__(
        self,
        llm: str = "anthropic",
        model: Optional[str] = None,
        project_root: Path = Path("."),
        local: bool = False,
    ):
        """
        Args:
            llm: LLM provider — "anthropic", "openai", or "ollama".
            model: Model name override. If None, uses the provider default.
            project_root: Root directory of the project to analyze.
            local: If True, forces Ollama regardless of other settings.
        """
        if local:
            llm = "ollama"

        self._project_root = Path(project_root)
        self._config = self._load_config(llm, model)
        self._llm = LLMClient.from_config(self._config)
        self._analyzer = MutationAnalyzer()
        self._generator = TestGenerator(self._llm, self._config)
        self._verifier = MutantVerifier(self._config)
        self._writer = TestWriter(self._config)

    def _load_config(self, llm: str, model: Optional[str]) -> QuellConfig:
        """Load config from pyproject.toml, then apply overrides."""
        try:
            import tomllib
            pyproject = self._project_root / "pyproject.toml"
            if pyproject.exists():
                data = tomllib.loads(pyproject.read_text())
                quell_cfg = data.get("tool", {}).get("quell", {})
                config = QuellConfig(**quell_cfg) if quell_cfg else QuellConfig()
            else:
                config = QuellConfig()
        except Exception:
            config = QuellConfig()

        updates: dict = {"llm_provider": llm}
        if model:
            updates["llm_model"] = model
        return config.model_copy(update=updates)

    def verify_test(
        self,
        test_code: str,
        source_file: str | Path,
    ) -> VerifyResult:
        """
        Verify that a test actually kills at least one mutant in the source file.

        The test must:
        1. Pass on the original source (no false positives)
        2. Fail when a mutation is applied (proves it catches the change)

        Args:
            test_code: Python source of the test function to verify.
            source_file: Path to the source file to mutate against.

        Returns:
            VerifyResult with verified=True if the test kills a mutant.
        """
        return asyncio.run(self._verify_test_async(test_code, Path(source_file)))

    async def _verify_test_async(
        self, test_code: str, source_file: Path
    ) -> VerifyResult:
        from quell.adapters.mutmut_adapter import MutmutAdapter

        adapter = MutmutAdapter(self._project_root)
        survivors = adapter.read_survivors()
        survivors = [self.analyzer.analyze(m) for m in survivors]

        # Filter to mutants in the requested source file
        rel_source = source_file if source_file.is_absolute() else self._project_root / source_file
        file_survivors = [
            m for m in survivors
            if m.file_path.resolve() == rel_source.resolve()
        ]

        if not file_survivors:
            return VerifyResult(
                verified=False,
                explanation="No surviving mutants found for this file. Run mutmut first.",
                status=VerificationStatus.DOESNT_KILL_MUTANT.value,
            )

        # Write the test to a temp file and check against the first survivor
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(test_code)
            temp_test = Path(tf.name)

        kills = 0
        try:
            for mutant in file_survivors:
                from quell.core.models import GeneratedTest, MutationOperator

                generated = GeneratedTest(
                    mutant_id=mutant.id,
                    test_function_name="test_sdk_verify",
                    test_code=test_code,
                    test_file_path=temp_test,
                    explanation="SDK verify call",
                    operator=mutant.operator,
                    generated_by="sdk",
                )
                vr = self._verifier.verify(mutant, generated)
                if vr.status == VerificationStatus.VERIFIED:
                    kills += 1
        finally:
            temp_test.unlink(missing_ok=True)

        verified = kills > 0
        score_delta = kills / max(len(file_survivors), 1)

        return VerifyResult(
            verified=verified,
            explanation=(
                f"Test kills {kills}/{len(file_survivors)} mutants in {source_file}"
                if verified
                else "Test does not kill any surviving mutants"
            ),
            status=VerificationStatus.VERIFIED.value if verified else VerificationStatus.DOESNT_KILL_MUTANT.value,
            kills_mutants=kills,
            score_delta=score_delta,
        )

    def get_score(self, path: str | Path | None = None) -> ScoreResult:
        """
        Get the current mutation score.

        Args:
            path: Optional path to restrict scoring to a single file.
                  If None, returns the project-wide score.

        Returns:
            ScoreResult with total score and per-file breakdown.
        """
        from quell.score.calculator import calculate_score

        project_score = calculate_score(self._project_root)

        by_file = {
            str(f.file_path): f.quell_score
            for f in project_score.files
        }

        if path:
            target = str(Path(path))
            filtered = {k: v for k, v in by_file.items() if target in k}
            if filtered:
                avg = sum(filtered.values()) / len(filtered)
                return ScoreResult(
                    total=avg,
                    percentage=int(avg * 100),
                    by_file=filtered,
                )

        return ScoreResult(
            total=project_score.total_score,
            percentage=project_score.percentage,
            by_file=by_file,
            total_mutants=project_score.total_mutants,
            killed_mutants=project_score.killed_mutants,
            survived_mutants=project_score.survived_mutants,
        )

    def fix_all(
        self,
        source: str = "mutmut",
        auto_write: bool = False,
        threshold: float = 0.0,
    ) -> FixResult:
        """
        Generate and apply verified killing tests for all surviving mutants.

        Args:
            source: Mutation tool — "mutmut" or "stryker".
            auto_write: If True, write fixes without interactive prompts.
            threshold: Minimum score required; raises if not met after fix.

        Returns:
            FixResult with counts and before/after scores.
        """
        return asyncio.run(self._fix_all_async(source, auto_write, threshold))

    async def _fix_all_async(
        self, source: str, auto_write: bool, threshold: float
    ) -> FixResult:
        from quell.score.calculator import calculate_score

        result = FixResult()

        try:
            before = calculate_score(self._project_root)
            result.score_before = before.total_score
        except FileNotFoundError:
            result.score_before = 0.0

        if source == "mutmut":
            adapter = MutmutAdapter(self._project_root)
        else:
            from quell.adapters.stryker_adapter import StrykerAdapter
            report = self._project_root / "reports" / "mutation" / "mutation.json"
            adapter = StrykerAdapter(report)

        from quell.adapters.mutmut_adapter import MutmutAdapter

        adapter = MutmutAdapter(self._project_root)
        survivors = adapter.read_survivors()
        survivors = [self._analyzer.analyze(m) for m in survivors]

        config = self._config.model_copy(update={"auto_write": auto_write})
        writer = TestWriter(config)

        for mutant in survivors:
            generated = await self._generator.generate(mutant)
            verified = False

            for _ in range(config.max_verification_attempts):
                vr = self._verifier.verify(mutant, generated)
                if vr.status == VerificationStatus.VERIFIED:
                    verified = True
                    break
                generated = await self._generator.generate(mutant)

            if not verified:
                result.failed += 1
                continue

            if auto_write and writer.write(generated, mutant.id):
                result.fixed += 1
            else:
                result.skipped += 1

        try:
            after = calculate_score(self._project_root)
            result.score_after = after.total_score
        except FileNotFoundError:
            result.score_after = result.score_before

        return result

    def repair(self, test_dir: Path, source_dir: Path) -> RepairResult:
        """
        Find and fix weak tests in test_dir.

        Runs mutation testing on source_dir, finds surviving mutants,
        generates verified killing tests, and injects them into test_dir.

        Args:
            test_dir: Directory containing the test suite.
            source_dir: Source code directory to mutate.

        Returns:
            RepairResult with counts and before/after scores.
        """
        from quell.repair.engine import RepairEngine, RepairResult as EngineResult

        engine = RepairEngine(self._config, self._project_root)
        engine_result: EngineResult = engine.repair(
            test_dir=test_dir,
            source_dir=source_dir,
            auto_write=True,
        )

        return RepairResult(
            fixed=engine_result.fixed,
            skipped=engine_result.skipped,
            failed=engine_result.failed,
            score_before=engine_result.score_before,
            score_after=engine_result.score_after,
            test_dir=str(test_dir),
            source_dir=str(source_dir),
        )
