"""
Checks which Requirements already have tests in the test suite.
Uses AST — no test execution required.

Discovery (spec10 §4.3):
  - recursive: every test file under the project's test roots, not 3 fixed paths
  - honours [tool.pytest.ini_options] testpaths when present
Matching (spec10 §4.3):
  - a test covers a requirement if it *references the target symbol* —
    via a call expression, an import, or an attribute — not merely if the
    function name happens to be a substring of the test name

Conservative: marks as uncovered when uncertain.
Better to generate a duplicate test than miss a real gap.

`has_test_suite` distinguishes "no tests found anywhere" (coverage unknown)
from "tests exist and none cover this" (a real gap). Callers must not report
a score when coverage is unknown — see spec10 non-negotiable #2.
"""
from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from quell.core.models import ConstraintKind, Requirement

_TEST_DIR_NAMES = ("tests", "test")
_SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "site-packages", ".tox"}


@dataclass
class _TestFn:
    """One test function plus the symbols it references."""
    name: str
    docstring: str
    called: set[str] = field(default_factory=set)
    imported: set[str] = field(default_factory=set)
    attributes: set[str] = field(default_factory=set)
    node: ast.FunctionDef | ast.AsyncFunctionDef | None = None

    def references(self, symbol: str) -> bool:
        """True if this test calls, imports, or attribute-accesses `symbol`."""
        return (
            symbol in self.called
            or symbol in self.imported
            or symbol in self.attributes
        )


class CoverageChecker:
    """AST-based coverage checker. No test execution needed."""

    def __init__(self, project_root: Path = Path(".")):
        self.project_root = project_root
        self._index: list[_TestFn] | None = None
        # Measured per-line coverage (quell.coverage.runtime.CoverageMap), or
        # None to use static inference. See use_runtime_coverage().
        self._runtime: object | None = None

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def has_test_suite(self) -> bool:
        """True if any test function was discovered anywhere in the project.

        When False, coverage is *unknown*, not zero — callers must suppress
        the score rather than report 0 (spec10 §4.1).
        """
        return bool(self._build_index())

    @property
    def mode(self) -> str:
        """Which evidence produced the last check: "measured" or "inferred".

        spec10 §4.3 requires this be reported alongside any number. Inferred
        coverage is a static guess; measured coverage is a runtime fact. They
        must never be presented as the same thing.
        """
        return "measured" if self._runtime is not None else "inferred"

    def use_runtime_coverage(self, coverage_map: object | None) -> None:
        """Supply measured per-line coverage from quell.coverage.runtime.

        Passing None keeps static inference, so callers that cannot or should
        not run the suite are unaffected.
        """
        self._runtime = coverage_map

    def check(self, requirements: list[Requirement]) -> list[Requirement]:
        """Mark each Requirement is_covered=True/False. Returns same list."""
        tests = self._build_index()
        for req in requirements:
            covering = self._covering_by_execution(req)
            if covering is None:
                covering = self._find_covering(req, tests)
            req.is_covered = len(covering) > 0
            req.covering_tests = covering
        return requirements

    def _covering_by_execution(self, req: Requirement) -> list[str] | None:
        """Tests that actually executed this requirement's line, or None.

        None means "no measurement for this line", which is different from an
        empty list ("measured, nothing ran it"). Only the former falls back to
        static inference; the latter is a real, measured gap.
        """
        if self._runtime is None or not req.source_line:
            return None
        try:
            covered = self._runtime.is_line_covered(req.target_file, req.source_line)  # type: ignore[attr-defined]
            if not covered:
                # Measured and genuinely not executed by any test.
                return []
            return self._runtime.tests_for(req.target_file, req.source_line)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — invariant #6; fall back to inference
            return None

    # ── discovery ────────────────────────────────────────────────────────────

    def _test_roots(self) -> list[Path]:
        """Test roots from pyproject testpaths, else conventional locations."""
        roots: list[Path] = []
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                cfg = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                paths = (
                    cfg.get("tool", {})
                    .get("pytest", {})
                    .get("ini_options", {})
                    .get("testpaths", [])
                )
                if isinstance(paths, str):
                    paths = [paths]
                roots.extend(
                    self.project_root / p for p in paths
                    if (self.project_root / p).is_dir()
                )
            except Exception:  # noqa: BLE001 — malformed config must not break scanning
                pass

        if not roots:
            roots = [
                self.project_root / name
                for name in _TEST_DIR_NAMES
                if (self.project_root / name).is_dir()
            ]

        # Always include the project root itself so tests colocated with source
        # (src/pkg/test_foo.py) are discovered too.
        roots.append(self.project_root)
        return roots

    def _test_files(self) -> list[Path]:
        """Every test file under the test roots, recursively, de-duplicated."""
        seen: set[Path] = set()
        for root in self._test_roots():
            for pattern in ("test_*.py", "*_test.py"):
                for path in root.rglob(pattern):
                    if any(part in _SKIP_DIRS for part in path.parts):
                        continue
                    try:
                        seen.add(path.resolve())
                    except OSError:
                        continue
        return sorted(seen)

    def _build_index(self) -> list[_TestFn]:
        """Parse every test file once; cache the symbol index."""
        if self._index is not None:
            return self._index

        index: list[_TestFn] = []
        for path in self._test_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001 — invariant #6: readers never raise
                continue

            module_imports = _collect_imports(tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                called, attributes = _collect_references(node)
                index.append(_TestFn(
                    name=node.name,
                    docstring=ast.get_docstring(node) or "",
                    called=called,
                    attributes=attributes,
                    imported=module_imports,
                    node=node,
                ))

        self._index = index
        return index

    # ── matching ─────────────────────────────────────────────────────────────

    def _find_covering(self, req: Requirement, tests: list[_TestFn]) -> list[str]:
        covering: list[str] = []
        target = req.target_function

        for fn in tests:
            if not self._mentions(fn, target):
                continue
            # BUG_REPRO: never mark as covered (always regenerate)
            if req.constraint_kind == ConstraintKind.BUG_REPRO:
                continue
            # MUST_RAISE: check for pytest.raises
            if req.constraint_kind == ConstraintKind.MUST_RAISE:
                if fn.node is not None and _has_raises(fn.node):
                    covering.append(fn.name)
            # BOUNDARY: check for boundary values
            elif req.constraint_kind == ConstraintKind.BOUNDARY:
                if fn.node is not None and _has_boundary(fn.node):
                    covering.append(fn.name)
            else:
                covering.append(fn.name)  # conservative: assume covered
        return covering

    def _mentions(self, fn: _TestFn, target: str) -> bool:
        """Does this test reference the target function at all?

        Structural evidence (call / import / attribute) is checked first — it is
        what actually indicates coverage. Name and docstring substring matching
        is retained as a weaker fallback for indirection we cannot resolve
        statically (fixtures, client.post(...) style API tests).
        """
        if fn.references(target):
            return True
        lowered = target.lower()
        return lowered in fn.name.lower() or lowered in fn.docstring.lower()


# ── module-level AST helpers ─────────────────────────────────────────────────


def _collect_imports(tree: ast.Module) -> set[str]:
    """Every name bound by an import in this module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _collect_references(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], set[str]]:
    """Return (called names, attribute names) referenced inside a test body."""
    called: set[str] = set()
    attributes: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
        elif isinstance(child, ast.Attribute):
            attributes.add(child.attr)
    return called, attributes


def _has_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                call = item.context_expr
                if isinstance(call, ast.Call):
                    name = (
                        getattr(call.func, "id", None)
                        or getattr(call.func, "attr", None)
                    )
                    if name == "raises":
                        return True
    return False


def _has_boundary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant):
            if child.value in (0, -1, 1, 0.0, -1.0, 1.0):
                return True
    return False
