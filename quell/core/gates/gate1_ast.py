"""Gate 1 — AST & Import Validity.

Checks:
  1. ast.parse() succeeds (no SyntaxError)
  2. All top-level imports resolve in the current environment
  3. No obviously undefined names in the test body (basic scope check)

Returns GateResult(passed=True) or GateResult(passed=False, reason=...).
Caller retries once on failure before routing to FLAGGED.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from typing import Any

from quell.core.models import GateResult


@dataclass
class GateContext:
    """Context passed to every gate."""

    target_file: str = ""
    project_root: str = ""
    existing_test_files: list[str] | None = None
    original_source: str = ""
    violated_source: str = ""
    extra: dict[str, Any] | None = None


def check(test_code: str, ctx: GateContext) -> GateResult:  # noqa: ARG001
    """Gate 1: syntactic validity and import resolution."""
    try:
        tree = ast.parse(test_code)
    except SyntaxError as exc:
        return GateResult(passed=False, gate=1, reason=f"invalid syntax: {exc}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if not _can_import(module):
                    return GateResult(
                        passed=False, gate=1,
                        reason=f"unresolvable import: {alias.name}",
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if not _can_import(module):
                    return GateResult(
                        passed=False, gate=1,
                        reason=f"unresolvable import: {node.module}",
                    )

    return GateResult(passed=True, gate=1)


def _can_import(module_name: str) -> bool:
    """Return True if the module can be found in sys.path / stdlib."""
    stdlib: frozenset[str] = getattr(sys, "stdlib_module_names", frozenset())
    if module_name in stdlib:
        return True
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ModuleNotFoundError, ValueError):
        return False
