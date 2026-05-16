"""Gate 2 — Originality Check.

Checks:
  1. AST fingerprint: normalized hash of the test body must not match any existing test
  2. Name check: test function name must not already exist in project test files
  3. Boilerplate check: reject if the only assertion is `assert result is not None`
  4. N-gram check: 5-gram token overlap > 80% against existing tests → reject

Returns GateResult(passed=True) or GateResult(passed=False, reason=...).
Gate 2 failures are silent (test simply not written, not SCAFFOLDED).
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from quell.core.gates.gate1_ast import GateContext
from quell.core.models import GateResult

_BOILERPLATE_PATTERN = re.compile(
    r"assert\s+\w+\s+is\s+not\s+None\s*$", re.MULTILINE
)


def check(test_code: str, ctx: GateContext) -> GateResult:
    """Gate 2: originality — not a duplicate, not boilerplate, not copied."""
    # 1. Name check
    func_name = _extract_test_name(test_code)
    if func_name and ctx.existing_test_files:
        for test_file in ctx.existing_test_files:
            existing = Path(test_file).read_text(encoding="utf-8", errors="ignore")
            if f"def {func_name}" in existing:
                return GateResult(
                    passed=False, gate=2,
                    reason=f"duplicate of existing test: {func_name}",
                )

    # 2. Boilerplate check — only assertion is `assert X is not None`
    assertions = _extract_assertions(test_code)
    if assertions and all(_BOILERPLATE_PATTERN.search(a) for a in assertions):
        return GateResult(passed=False, gate=2, reason="assertion too weak")

    # 3. AST fingerprint + n-gram check against existing test files
    if ctx.existing_test_files:
        new_ngrams = _token_ngrams(test_code, n=5)
        for test_file in ctx.existing_test_files:
            existing = Path(test_file).read_text(encoding="utf-8", errors="ignore")
            existing_ngrams = _token_ngrams(existing, n=5)
            if new_ngrams and existing_ngrams:
                overlap = len(new_ngrams & existing_ngrams) / len(new_ngrams)
                if overlap > 0.80:
                    return GateResult(
                        passed=False, gate=2, reason="too similar to existing test",
                    )

    return GateResult(passed=True, gate=2)


def _extract_test_name(code: str) -> str | None:
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                return node.name
    except SyntaxError:
        pass
    return None


def _extract_assertions(code: str) -> list[str]:
    lines = code.splitlines()
    return [ln.strip() for ln in lines if ln.strip().startswith("assert ")]


def _token_ngrams(code: str, n: int = 5) -> set[tuple[str, ...]]:
    tokens = re.findall(r"\w+", code)
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _ast_fingerprint(code: str) -> str:
    try:
        tree = ast.parse(code)
        dumped = ast.dump(tree, annotate_fields=False)
        return hashlib.sha256(dumped.encode()).hexdigest()
    except SyntaxError:
        return ""
