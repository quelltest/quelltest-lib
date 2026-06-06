"""Unit tests for DocstringReader."""
from __future__ import annotations

from pathlib import Path

from quell.core.models import ConstraintKind, SpecSource
from quell.spec.docstring_reader import DocstringReader


def test_reads_must_raise(sample_payments_path: Path) -> None:
    reader = DocstringReader()
    reqs = reader.read(sample_payments_path)
    must_raise = [r for r in reqs if r.constraint_kind == ConstraintKind.MUST_RAISE]
    assert len(must_raise) >= 1
    assert any("ValueError" in r.description for r in must_raise)


def test_reads_boundary(sample_payments_path: Path) -> None:
    reader = DocstringReader()
    reqs = reader.read(sample_payments_path)
    boundary = [r for r in reqs if r.constraint_kind == ConstraintKind.BOUNDARY]
    assert len(boundary) >= 1


def test_reads_must_return(sample_payments_path: Path) -> None:
    reader = DocstringReader()
    reqs = reader.read(sample_payments_path)
    returns = [r for r in reqs if r.constraint_kind == ConstraintKind.MUST_RETURN]
    assert len(returns) >= 1


def test_source_is_docstring(sample_payments_path: Path) -> None:
    reader = DocstringReader()
    reqs = reader.read(sample_payments_path)
    assert all(r.source == SpecSource.DOCSTRING for r in reqs)


def test_returns_empty_on_bad_file() -> None:
    reader = DocstringReader()
    result = reader.read(Path("/nonexistent/file.py"))
    assert result == []


def test_returns_empty_on_no_docstrings(tmp_path: Path) -> None:
    f = tmp_path / "nodoc.py"
    f.write_text("def foo(x): return x\n")
    reader = DocstringReader()
    assert reader.read(f) == []


def test_target_function_set_correctly(sample_payments_path: Path) -> None:
    reader = DocstringReader()
    reqs = reader.read(sample_payments_path)
    funcs = {r.target_function for r in reqs}
    assert "process_payment" in funcs or "apply_discount" in funcs


def test_source_name() -> None:
    assert DocstringReader().source_name == "docstring"


class TestMultilineRaises:
    """Regression tests for issue #4 — multiline Raises: continuation lines."""

    def _read(self, tmp_path: Path, src: str) -> list:
        f = tmp_path / "mod.py"
        f.write_text(src)
        return DocstringReader().read(f)

    def test_single_line_raises_still_works(self, tmp_path: Path) -> None:
        src = '''
def pay(amount):
    """
    Raises:
        ValueError: if amount <= 0
    """
'''
        reqs = self._read(tmp_path, src)
        assert len(reqs) == 1
        assert "ValueError" in reqs[0].description

    def test_multiline_condition_captured(self, tmp_path: Path) -> None:
        src = '''
def pay(amount, currency):
    """
    Raises:
        ValueError: if amount <= 0,
            or if currency is unsupported
    """
'''
        reqs = self._read(tmp_path, src)
        assert len(reqs) == 1
        assert "ValueError" in reqs[0].description
        assert "unsupported" in reqs[0].description

    def test_two_exceptions_each_captured(self, tmp_path: Path) -> None:
        src = '''
def pay(amount, currency):
    """
    Raises:
        ValueError: if amount <= 0
        TypeError: if currency is not a string
    """
'''
        reqs = self._read(tmp_path, src)
        kinds = {r.description for r in reqs}
        assert any("ValueError" in d for d in kinds)
        assert any("TypeError" in d for d in kinds)

    def test_second_exception_with_continuation(self, tmp_path: Path) -> None:
        src = '''
def pay(amount, currency):
    """
    Raises:
        ValueError: if amount <= 0,
            or negative
        TypeError: if currency is not a string,
            must be ISO 4217
    """
'''
        reqs = self._read(tmp_path, src)
        assert len(reqs) == 2
        assert any("negative" in r.description for r in reqs)
        assert any("ISO 4217" in r.description for r in reqs)
