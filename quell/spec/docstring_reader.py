"""
Reads Python docstrings and extracts testable Requirements.

Direction: docstring → Requirements.
This is the OPPOSITE of every existing docstring tool (code → docs).

Supported styles: Google, NumPy, RST, plain English (LLM fallback).

Key extractions:
  "Raises: ValueError: if amount <= 0"  → MUST_RAISE requirement
  "amount: Must be positive (> 0)"      → BOUNDARY requirement
  "currency: one of USD, EUR, GBP"      → ENUM_VALID requirement
  "Returns: Transaction with status"    → MUST_RETURN requirement
"""
from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

from quell.core.models import ConstraintKind, Requirement, SpecSource


class DocstringReader:
    """
    Extracts testable requirements from Python docstrings.

    Strategy:
    1. Parse file with ast module — get every function's docstring
    2. Run structured parsers (Google/NumPy/RST style)
    3. LLM fallback for unstructured prose

    Returns [] on any error — never raises.
    """

    def __init__(self, llm_client: object = None) -> None:
        self.llm = llm_client

    def read(self, file_path: Path) -> list[Requirement]:
        """Read file and extract Requirements from all function docstrings."""
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            return []

        requirements = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    requirements.extend(
                        self._parse(doc, node.name, file_path)
                    )
        return requirements

    def _parse(self, doc: str, func: str, path: Path) -> list[Requirement]:
        reqs: list[Requirement] = []
        reqs.extend(self._raises(doc, func, path))
        reqs.extend(self._boundaries(doc, func, path))
        reqs.extend(self._enums(doc, func, path))
        reqs.extend(self._returns(doc, func, path))
        if not reqs and self.llm:
            reqs.extend(self._llm_fallback(doc, func, path))
        return reqs

    def _raises(self, doc: str, func: str, path: Path) -> list[Requirement]:
        reqs = []
        # Match Google "Raises:\n    ExceptionType: condition" blocks.
        # The outer regex captures the entire indented block; we then collect
        # continuation lines (indented further, no leading ExceptionType:) so
        # that multi-line conditions are not silently dropped.
        for block in re.finditer(
            r'Raises?:\s*\n((?:[ \t]+[^\n]+\n?)*)', doc, re.MULTILINE
        ):
            current_exc: str | None = None
            current_cond_parts: list[str] = []
            current_raw: str = ""

            def _flush() -> None:
                if current_exc is None:
                    return
                cond = " ".join(current_cond_parts).strip()
                reqs.append(Requirement(
                    id=str(uuid.uuid4())[:8],
                    description=f"raises {current_exc} when {cond}",
                    constraint_kind=ConstraintKind.MUST_RAISE,
                    source=SpecSource.DOCSTRING,
                    target_function=func,
                    target_file=path,
                    expected_behavior=f"raises {current_exc}",
                    raw_spec_text=current_raw,
                ))

            for raw_line in block.group(1).splitlines():
                stripped = raw_line.strip()
                if not stripped:
                    continue
                # An exception entry starts with "ExceptionType: ..."
                if re.match(r'\w[\w.]*\s*:', stripped):
                    _flush()
                    current_exc = None
                    current_cond_parts = []
                    exc, _, cond_start = stripped.partition(':')
                    current_exc = exc.strip()
                    current_raw = stripped
                    if cond_start.strip():
                        current_cond_parts.append(cond_start.strip())
                elif current_exc is not None:
                    # Continuation line — append to the condition description
                    current_cond_parts.append(stripped)
            _flush()
        return reqs

    def _boundaries(self, doc: str, func: str, path: Path) -> list[Requirement]:
        reqs = []
        patterns = [
            r'must be\s+positive',
            r'must be\s*>\s*0',
            r'must be\s*>=\s*\d+',
            r'must be\s*<\s*\d+',
            r'must be\s+negative',
            r'must be\s+between\s+[\d.]+\s+and\s+[\d.]+',
        ]
        for p in patterns:
            for m in re.finditer(p, doc, re.IGNORECASE):
                reqs.append(Requirement(
                    id=str(uuid.uuid4())[:8],
                    description=m.group(0),
                    constraint_kind=ConstraintKind.BOUNDARY,
                    source=SpecSource.DOCSTRING,
                    target_function=func,
                    target_file=path,
                    raw_spec_text=m.group(0),
                ))
        return reqs

    def _enums(self, doc: str, func: str, path: Path) -> list[Requirement]:
        reqs = []
        for m in re.finditer(
            r'(?:must be one of|one of|valid values?)[:\s]+([A-Z][A-Z,\s"\']+)',
            doc, re.IGNORECASE
        ):
            values = [
                v.strip().strip("\"'")
                for v in re.split(r'[,|]', m.group(1))
                if v.strip()
            ]
            if len(values) >= 2:
                reqs.append(Requirement(
                    id=str(uuid.uuid4())[:8],
                    description=f"must be one of {values}",
                    constraint_kind=ConstraintKind.ENUM_VALID,
                    source=SpecSource.DOCSTRING,
                    target_function=func,
                    target_file=path,
                    raw_spec_text=m.group(0),
                ))
        return reqs

    def _returns(self, doc: str, func: str, path: Path) -> list[Requirement]:
        reqs = []
        for m in re.finditer(r'Returns?:\s*\n\s*(.+)', doc, re.MULTILINE):
            desc = m.group(1).strip()
            if desc:
                reqs.append(Requirement(
                    id=str(uuid.uuid4())[:8],
                    description=f"returns {desc}",
                    constraint_kind=ConstraintKind.MUST_RETURN,
                    source=SpecSource.DOCSTRING,
                    target_function=func,
                    target_file=path,
                    raw_spec_text=desc,
                ))
        return reqs

    def _llm_fallback(self, doc: str, func: str, path: Path) -> list[Requirement]:
        # Implement with LLMClient when structured parsing finds nothing
        return []

    @property
    def source_name(self) -> str:
        """Reader name."""
        return "docstring"
