"""Unit tests for RuleEngine."""
from __future__ import annotations

from pathlib import Path

from quell.core.models import ConstraintKind, Requirement, SpecSource
from quell.synthesis.rule_engine import RuleEngine


def _req(kind: ConstraintKind, path: Path) -> Requirement:
    return Requirement(
        id="abc123",
        description=f"test {kind.value}",
        constraint_kind=kind,
        source=SpecSource.DOCSTRING,
        target_function="process_payment",
        target_file=path / "src" / "payments.py",
    )


def test_can_handle_must_raise(tmp_path: Path) -> None:
    assert RuleEngine().can_handle(_req(ConstraintKind.MUST_RAISE, tmp_path))


def test_can_handle_boundary(tmp_path: Path) -> None:
    assert RuleEngine().can_handle(_req(ConstraintKind.BOUNDARY, tmp_path))


def test_can_handle_enum_valid(tmp_path: Path) -> None:
    assert RuleEngine().can_handle(_req(ConstraintKind.ENUM_VALID, tmp_path))


def test_can_handle_custom(tmp_path: Path) -> None:
    assert RuleEngine().can_handle(_req(ConstraintKind.CUSTOM, tmp_path))


def test_generate_must_raise_returns_test(tmp_path: Path) -> None:
    req = _req(ConstraintKind.MUST_RAISE, tmp_path)
    req.expected_behavior = "raises ValueError"
    engine = RuleEngine()
    test = engine.generate(req)
    assert test is not None
    assert test.test_function_name.startswith("test_quell_")
    assert "ValueError" in test.test_code


def test_generate_boundary_returns_test(tmp_path: Path) -> None:
    req = _req(ConstraintKind.BOUNDARY, tmp_path)
    req.description = "must be positive"
    engine = RuleEngine()
    test = engine.generate(req)
    assert test is not None
    assert "0" in test.test_code


def test_generate_enum_returns_test(tmp_path: Path) -> None:
    req = _req(ConstraintKind.ENUM_VALID, tmp_path)
    engine = RuleEngine()
    test = engine.generate(req)
    assert test is not None
    assert "INVALID_VALUE" in test.test_code


def test_generate_custom_returns_test(tmp_path: Path) -> None:
    req = _req(ConstraintKind.CUSTOM, tmp_path)
    engine = RuleEngine()
    # CUSTOM is handled — sig not found for non-existent function generates a minimal stub
    test = engine.generate(req)
    assert test is not None
    assert test.test_function_name.startswith("test_quell_")


def test_generated_by_is_rule_engine(tmp_path: Path) -> None:
    req = _req(ConstraintKind.MUST_RAISE, tmp_path)
    test = RuleEngine().generate(req)
    assert test is not None
    assert test.generated_by == "rule_engine"
