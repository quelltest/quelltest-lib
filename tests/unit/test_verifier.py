"""Unit tests for Verifier (spec3 architecture)."""
from __future__ import annotations

from pathlib import Path

import pytest

from quell.core.models import (
    ConstraintKind,
    GeneratedTest,
    QuellConfig,
    Requirement,
    SpecSource,
    VerificationStatus,
)
from quell.core.verifier import Verifier


@pytest.fixture
def verifier(default_config: QuellConfig) -> Verifier:
    return Verifier(default_config)


class TestWriteTemp:
    def test_creates_temp_file(
        self, verifier: Verifier, sample_generated_test: GeneratedTest
    ) -> None:
        temp = verifier._write_temp(sample_generated_test)
        assert temp.exists()
        assert "quell_" in temp.name
        temp.unlink(missing_ok=True)

    def test_temp_file_contains_test_code(
        self, verifier: Verifier, sample_generated_test: GeneratedTest
    ) -> None:
        temp = verifier._write_temp(sample_generated_test)
        content = temp.read_text()
        assert sample_generated_test.test_function_name in content
        temp.unlink(missing_ok=True)


class TestBackupRestore:
    def test_backup_creates_copy(self, verifier: Verifier, tmp_path: Path) -> None:
        src = tmp_path / "source.py"
        src.write_text("x = 1\n")
        bak = verifier._backup(src)
        assert bak.exists()
        assert bak.read_text() == "x = 1\n"

    def test_restore_overwrites_source(self, verifier: Verifier, tmp_path: Path) -> None:
        src = tmp_path / "source.py"
        src.write_text("x = 1\n")
        bak = verifier._backup(src)
        src.write_text("x = 999\n")
        verifier._restore(src, bak)
        assert src.read_text() == "x = 1\n"
        assert not bak.exists()


class TestViolate:
    def test_must_raise_comments_out_raise(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        src = tmp_path / "code.py"
        src.write_text("def foo(x):\n    raise ValueError('bad')\n    return x\n")
        req = Requirement(
            id="v001", description="raises ValueError",
            constraint_kind=ConstraintKind.MUST_RAISE,
            source=SpecSource.DOCSTRING,
            target_function="foo", target_file=src,
        )
        verifier._violate(req)
        assert "# QUELL_VIOLATION" in src.read_text()

    def test_bug_repro_skips_violation(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        src = tmp_path / "code.py"
        original = "def foo(): return 1\n"
        src.write_text(original)
        req = Requirement(
            id="v002", description="bug",
            constraint_kind=ConstraintKind.BUG_REPRO,
            source=SpecSource.BUG_REPORT,
            target_function="foo", target_file=src,
        )
        verifier._violate(req)
        assert src.read_text() == original  # untouched


class TestPytest:
    def test_passing_test_returns_passed_true(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test_pass.py"
        test_file.write_text("def test_always_passes():\n    assert True\n")
        src = tmp_path / "source.py"
        src.write_text("x = 1\n")
        result = verifier._pytest(test_file, src)
        assert result["passed"] is True

    def test_failing_test_returns_passed_false(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_always_fails():\n    assert False\n")
        src = tmp_path / "source.py"
        src.write_text("x = 1\n")
        result = verifier._pytest(test_file, src)
        assert result["passed"] is False


class TestVerifyFull:
    def test_source_restored_after_verify(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        src = tmp_path / "payments.py"
        original = "def foo():\n    return 1\n"
        src.write_text(original)

        req = Requirement(
            id="v003", description="test",
            constraint_kind=ConstraintKind.MUST_RETURN,
            source=SpecSource.DOCSTRING,
            target_function="foo", target_file=src,
        )
        test = GeneratedTest(
            requirement_id="v003",
            test_function_name="test_quell_foo_v003",
            test_code="def test_quell_foo_v003():\n    assert True\n",
            test_file_path=tmp_path / "tests" / "test_payments.py",
            explanation="test",
            generated_by="rule_engine",
        )
        verifier.verify(req, test)
        assert src.read_text() == original

    def test_fails_on_correct_status_when_test_fails(
        self, verifier: Verifier, tmp_path: Path
    ) -> None:
        src = tmp_path / "payments.py"
        src.write_text("def foo():\n    return 1\n")

        req = Requirement(
            id="v004", description="test",
            constraint_kind=ConstraintKind.MUST_RETURN,
            source=SpecSource.DOCSTRING,
            target_function="foo", target_file=src,
        )
        test = GeneratedTest(
            requirement_id="v004",
            test_function_name="test_quell_foo_v004",
            test_code="def test_quell_foo_v004():\n    assert False\n",
            test_file_path=tmp_path / "tests" / "test_payments.py",
            explanation="test",
            generated_by="rule_engine",
        )
        result = verifier.verify(req, test)
        assert result.status == VerificationStatus.FAILS_ON_CORRECT


class TestBackupFilenameCollision:
    """Regression tests for issue #3 — backup filename collision."""

    def test_backup_names_are_unique(self, tmp_path: Path, default_config: QuellConfig) -> None:
        v = Verifier(default_config, project_root=tmp_path)
        src = tmp_path / "payments.py"
        src.write_text("def foo(): pass\n")
        names = {v._backup(src).name for _ in range(5)}
        assert len(names) == 5, "backup filenames must be unique across concurrent calls"

    def test_backup_uses_hex_not_timestamp(self, tmp_path: Path, default_config: QuellConfig) -> None:
        v = Verifier(default_config, project_root=tmp_path)
        src = tmp_path / "payments.py"
        src.write_text("def foo(): pass\n")
        bak = v._backup(src)
        # uuid4 hex is 32 hex chars; a unix timestamp has at most 10 digits
        suffix = bak.stem.split("_")[-1]
        assert len(suffix) == 32, f"expected 32-char uuid hex, got: {suffix!r}"
