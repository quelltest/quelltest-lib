from __future__ import annotations

from pathlib import Path
import pytest

from quell.core.models import ConstraintKind, Requirement, SpecSource
from quell.synthesis.pyspark_rule_engine import PySparkRuleEngine


def test_pyspark_rule_engine_can_handle() -> None:
    engine = PySparkRuleEngine()
    req_not_null = Requirement(
        id="r1", description="not null",
        constraint_kind=ConstraintKind.NOT_NULL,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py")
    )
    req_type_check = Requirement(
        id="r2", description="type check",
        constraint_kind=ConstraintKind.TYPE_CHECK,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py")
    )
    req_boundary = Requirement(
        id="r3", description="boundary",
        constraint_kind=ConstraintKind.BOUNDARY,
        source=SpecSource.DOCSTRING,
        target_function="foo", target_file=Path("source.py")
    )

    assert engine.can_handle(req_not_null) is True
    assert engine.can_handle(req_type_check) is True
    assert engine.can_handle(req_boundary) is False


def test_pyspark_rule_engine_validation() -> None:
    engine = PySparkRuleEngine()

    # Valid case
    req_valid = Requirement(
        id="r1", description="not null",
        constraint_kind=ConstraintKind.NOT_NULL,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py"),
        violation_input={"column": "my_col"}
    )
    test = engine.generate(req_valid)
    assert test is not None
    assert "my_col" in test.test_code

    # Invalid column name injection
    req_invalid_col = Requirement(
        id="r2", description="not null",
        constraint_kind=ConstraintKind.NOT_NULL,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py"),
        violation_input={"column": 'col"; import os; os.system("evil"); #'}
    )
    with pytest.raises(ValueError, match="Invalid PySpark column name"):
        engine.generate(req_invalid_col)


def test_pyspark_rule_engine_type_check_validation() -> None:
    engine = PySparkRuleEngine()

    # Valid type check
    req_valid = Requirement(
        id="r3", description="type check",
        constraint_kind=ConstraintKind.TYPE_CHECK,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py"),
        violation_input={"column": "my_col", "type": "IntegerType"}
    )
    test = engine.generate(req_valid)
    assert test is not None
    assert "IntegerType" in test.test_code

    # Invalid type check name injection
    req_invalid_type = Requirement(
        id="r4", description="type check",
        constraint_kind=ConstraintKind.TYPE_CHECK,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py"),
        violation_input={"column": "my_col", "type": "IntegerType\nimport os"}
    )
    with pytest.raises(ValueError, match="Invalid PySpark type name"):
        engine.generate(req_invalid_type)

    # Valid type check name but not whitelisted
    req_non_whitelisted_type = Requirement(
        id="r5", description="type check",
        constraint_kind=ConstraintKind.TYPE_CHECK,
        source=SpecSource.PYSPARK,
        target_function="foo", target_file=Path("source.py"),
        violation_input={"column": "my_col", "type": "MyCustomType"}
    )
    with pytest.raises(ValueError, match="Invalid PySpark type name"):
        engine.generate(req_non_whitelisted_type)
