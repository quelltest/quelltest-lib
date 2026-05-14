"""
End-to-end integration tests for Quell (spec3 architecture).

Tests the full pipeline:
  spec readers → Requirements → coverage checker → rule engine → verifier → writer
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from quell.core.models import ConstraintKind, QuellConfig
from quell.core.verifier import Verifier
from quell.core.writer import Writer
from quell.coverage.checker import CoverageChecker
from quell.llm.client import LLMClient
from quell.spec.docstring_reader import DocstringReader
from quell.spec.type_reader import TypeReader
from quell.synthesis.rule_engine import RuleEngine


@pytest.fixture
def e2e_config(tmp_path: Path) -> QuellConfig:
    return QuellConfig(
        backup_dir=tmp_path / ".quell" / "backups",
        audit_log_path=tmp_path / ".quell" / "audit.jsonl",
    )


@pytest.fixture
def mock_llm() -> LLMClient:
    llm = MagicMock(spec=LLMClient)
    llm.generate = AsyncMock(return_value=(
        "```python\n"
        "def test_quell_process_payment_abc():\n"
        '    """Proves: raises ValueError when amount is zero."""\n'
        "    import pytest\n"
        "    from tests.fixtures.sample_project.src.payments import PaymentRequest, process_payment\n"
        "    with pytest.raises(ValueError):\n"
        "        req = PaymentRequest(amount=-1, currency='USD', description='test')\n"
        "        process_payment(req)\n"
        "```"
    ))
    return llm


class TestDocstringReaderIntegration:
    def test_reads_all_requirement_kinds(self, sample_payments_path: Path) -> None:
        reader = DocstringReader()
        reqs = reader.read(sample_payments_path)
        kinds = {r.constraint_kind for r in reqs}
        assert ConstraintKind.MUST_RAISE in kinds
        assert ConstraintKind.BOUNDARY in kinds
        assert ConstraintKind.MUST_RETURN in kinds

    def test_all_reqs_have_target_file(self, sample_payments_path: Path) -> None:
        reqs = DocstringReader().read(sample_payments_path)
        assert all(r.target_file == sample_payments_path for r in reqs)


class TestTypeReaderIntegration:
    def test_reads_pydantic_constraints(self, sample_payments_path: Path) -> None:
        reader = TypeReader()
        reqs = reader.read(sample_payments_path)
        assert len(reqs) >= 3  # amount gt=0, currency Literal, description min_length

    def test_enum_requirement_has_usd(self, sample_payments_path: Path) -> None:
        reqs = TypeReader().read(sample_payments_path)
        enum_reqs = [r for r in reqs if r.constraint_kind == ConstraintKind.ENUM_VALID]
        assert any("USD" in r.description for r in enum_reqs)


class TestCoverageCheckerIntegration:
    def test_marks_uncovered_for_missing_tests(
        self, sample_payments_path: Path, tmp_path: Path
    ) -> None:
        reqs = DocstringReader().read(sample_payments_path)
        checker = CoverageChecker(tmp_path)  # tmp_path has no test files
        result = checker.check(reqs)
        assert all(not r.is_covered for r in result)


class TestRuleEnginePipeline:
    def test_generates_test_for_must_raise(self, sample_payments_path: Path) -> None:
        reqs = DocstringReader().read(sample_payments_path)
        must_raise = [r for r in reqs if r.constraint_kind == ConstraintKind.MUST_RAISE]
        assert must_raise

        engine = RuleEngine()
        # _all_required_unknown skips requirements whose only param is a complex
        # object type (e.g. PaymentRequest). Iterate to find first generatable one.
        test = None
        for r in must_raise:
            t = engine.generate(r)
            if t is not None:
                test = t
                break
        assert test is not None
        assert test.test_function_name.startswith("test_quell_")
        assert test.generated_by == "rule_engine"


class TestVerifierIntegration:
    def test_verifier_restores_source(
        self, e2e_config: QuellConfig, sample_payments_path: Path, tmp_path: Path
    ) -> None:
        # Copy source to tmp so we don't modify fixture
        src = tmp_path / "payments.py"
        src.write_text(sample_payments_path.read_text())

        reqs = DocstringReader().read(sample_payments_path)
        must_raise = [r for r in reqs if r.constraint_kind == ConstraintKind.MUST_RAISE]

        engine = RuleEngine()
        # Pick first requirement that can be generated (skips unknown-type-only params)
        req = None
        test = None
        for r in must_raise:
            t = engine.generate(r)
            if t is not None:
                req = r
                test = t
                break
        assert test is not None
        assert req is not None
        req.target_file = src

        original_content = src.read_text()
        verifier = Verifier(e2e_config)
        verifier.verify(req, test)

        assert src.read_text() == original_content


class TestWriterIntegration:
    def test_writer_creates_and_injects(
        self, e2e_config: QuellConfig, tmp_path: Path, sample_generated_test: object
    ) -> None:
        test_file = tmp_path / "test_output.py"
        test = sample_generated_test.model_copy(update={"test_file_path": test_file})  # type: ignore[union-attr]
        writer = Writer(e2e_config)
        success = writer.write(test, "test001")
        assert success
        assert test_file.exists()
        assert "test_quell_" in test_file.read_text()
