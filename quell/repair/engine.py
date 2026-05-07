"""
Quell Repair Engine — finds and strengthens weak AI-generated test suites.

`quell repair` is different from `quell fix`:
  - `quell fix`    reads results the user ran manually (mutmut/Stryker)
  - `quell repair` runs mutation testing internally, finds gaps, fixes them
                   — zero manual steps required

Target use case: teams using Copilot, Cursor, or Qodo to generate tests
want a single command to verify those tests actually catch bugs.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from quell.core.models import QuellConfig, VerificationStatus
from quell.core.analyzer import MutationAnalyzer
from quell.core.generator import TestGenerator
from quell.core.verifier import MutantVerifier
from quell.core.writer import TestWriter
from quell.adapters.mutmut_adapter import MutmutAdapter
from quell.ci.runner import run_mutmut_full
from quell.llm.client import LLMClient


@dataclass
class RepairResult:
    """Summary of a repair run."""

    fixed: int = 0
    skipped: int = 0
    failed: int = 0
    score_before: float = 0.0
    score_after: float = 0.0
    test_dir: Path = field(default_factory=lambda: Path("tests/"))
    source_dir: Path = field(default_factory=lambda: Path("src/"))

    @property
    def total(self) -> int:
        return self.fixed + self.skipped + self.failed

    @property
    def score_delta(self) -> float:
        return self.score_after - self.score_before


class RepairEngine:
    """
    Orchestrates the full repair pipeline:
    1. Run mutmut on the project (or reuse existing cache)
    2. Find all surviving mutants
    3. Generate + verify + write killing tests for each
    4. Return a RepairResult summary

    This is the zero-manual-step path: users point it at a test directory
    and it handles everything internally.
    """

    def __init__(self, config: QuellConfig, project_root: Path = Path(".")):
        self.config = config
        self.project_root = project_root
        self.llm = LLMClient.from_config(config)
        self.generator = TestGenerator(self.llm, config)
        self.verifier = MutantVerifier(config)
        self.writer = TestWriter(config)
        self.analyzer = MutationAnalyzer()

    def repair(
        self,
        test_dir: Path,
        source_dir: Path,
        show_only: bool = False,
        auto_write: bool = False,
    ) -> RepairResult:
        """
        Run the full repair pipeline synchronously.

        Args:
            test_dir: Directory containing the test suite to repair.
            source_dir: Source directory to mutate.
            show_only: If True, show what's weak without writing any fixes.
            auto_write: If True, write fixes without prompting.

        Returns:
            RepairResult summary.
        """
        return asyncio.run(
            self._repair_async(test_dir, source_dir, show_only, auto_write)
        )

    async def _repair_async(
        self,
        test_dir: Path,
        source_dir: Path,
        show_only: bool,
        auto_write: bool,
    ) -> RepairResult:
        result = RepairResult(test_dir=test_dir, source_dir=source_dir)

        # Record score before repair
        try:
            from quell.score.calculator import calculate_score
            before = calculate_score(self.project_root)
            result.score_before = before.total_score
        except FileNotFoundError:
            # No cache yet — run mutmut first
            run_mutmut_full(self.project_root)
            try:
                from quell.score.calculator import calculate_score
                before = calculate_score(self.project_root)
                result.score_before = before.total_score
            except FileNotFoundError:
                result.score_before = 0.0

        # Read survivors and run the fix loop
        adapter = MutmutAdapter(self.project_root)
        survivors = adapter.read_survivors()
        survivors = [self.analyzer.analyze(m) for m in survivors]

        config = self.config.model_copy(update={"auto_write": auto_write})

        for mutant in survivors:
            generated = await self.generator.generate(mutant)

            verified = False
            for _ in range(config.max_verification_attempts):
                vr = self.verifier.verify(mutant, generated)
                if vr.status == VerificationStatus.VERIFIED:
                    verified = True
                    break
                generated = await self.generator.generate(mutant)

            if not verified:
                result.failed += 1
                continue

            if show_only:
                result.skipped += 1
                continue

            if self.writer.write(generated, mutant.id):
                result.fixed += 1
            else:
                result.failed += 1

        # Record score after repair
        try:
            from quell.score.calculator import calculate_score
            after = calculate_score(self.project_root)
            result.score_after = after.total_score
        except FileNotFoundError:
            result.score_after = result.score_before

        return result
