"""Unit tests for SCAFFOLDED stub writer (spec7 §2.3, issue #41)."""
from __future__ import annotations

from pathlib import Path

from quell.core.models import ConstraintKind, Requirement, SpecSource
from quell.core.scaffold import (
    ensure_scaffold_gitignored,
    write_scaffold_stub,
)


def _req(tmp_path: Path) -> Requirement:
    src = tmp_path / "payments.py"
    src.write_text("def pay(amount): pass\n")
    return Requirement(
        id="req-scaffold-1",
        description="raises ValueError when amount <= 0",
        constraint_kind=ConstraintKind.MUST_RAISE,
        source=SpecSource.DOCSTRING,
        target_function="pay",
        target_file=src,
        raw_spec_text="if amount <= 0: raise ValueError",
        source_line=1,
    )


class TestWriteScaffoldStub:
    def test_creates_stub_file(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        path = write_scaffold_stub(req, None, 2, scaffold_dir)
        assert path.exists()
        assert path.name == "test_payments.py"

    def test_stub_contains_function(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        path = write_scaffold_stub(req, None, 2, scaffold_dir)
        content = path.read_text()
        assert "def test_quell_scaffold_" in content

    def test_stub_contains_todo_comment(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        path = write_scaffold_stub(req, None, 2, scaffold_dir)
        content = path.read_text()
        assert "quell: complete assertion" in content or "TODO" in content

    def test_stub_has_header_on_new_file(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        path = write_scaffold_stub(req, None, 2, scaffold_dir)
        content = path.read_text()
        assert "quell: scaffold" in content

    def test_duplicate_requirement_not_appended_twice(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        write_scaffold_stub(req, None, 2, scaffold_dir)
        write_scaffold_stub(req, None, 2, scaffold_dir)
        path = scaffold_dir / "test_payments.py"
        content = path.read_text()
        func_name = "test_quell_scaffold_pay_req_scaffold_1"
        assert content.count(func_name) == 1

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "a" / "b" / "scaffold"
        path = write_scaffold_stub(req, None, 2, scaffold_dir)
        assert path.parent.exists()

    def test_gates_passed_in_docstring(self, tmp_path: Path) -> None:
        req = _req(tmp_path)
        scaffold_dir = tmp_path / "tests" / "scaffold"
        path = write_scaffold_stub(req, None, 3, scaffold_dir)
        content = path.read_text()
        assert "3/5" in content or "3" in content


class TestEnsureScaffoldGitignored:
    def test_creates_gitignore_when_missing(self, tmp_path: Path) -> None:
        scaffold_dir = tmp_path / "tests" / "scaffold"
        ensure_scaffold_gitignored(tmp_path, scaffold_dir)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert "scaffold" in gitignore.read_text()

    def test_appends_to_existing_gitignore(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")
        scaffold_dir = tmp_path / "tests" / "scaffold"
        ensure_scaffold_gitignored(tmp_path, scaffold_dir)
        content = gitignore.read_text()
        assert "*.pyc" in content
        assert "scaffold" in content

    def test_idempotent_when_already_gitignored(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("tests/scaffold/\n")
        scaffold_dir = tmp_path / "tests" / "scaffold"
        ensure_scaffold_gitignored(tmp_path, scaffold_dir)
        content = gitignore.read_text()
        assert content.count("scaffold") == 1
