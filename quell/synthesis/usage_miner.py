"""
Mines real construction sites so generated tests build objects the way the
project already builds them.  (spec10 §4.4 rung 2, issue #144)

Rung 1 (fixture_locator, #143) covers parameters a conftest fixture can supply.
This covers the rest: a parameter typed `Team` where no `team` fixture exists,
but the repo constructs `Team(id=1, owner_id=42)` in a dozen places already.

Reusing a real call beats inventing one for the same reason a real fixture does
— the project knows its own required arguments, invariants and defaults, and we
do not. MocklessTester (arXiv 2605.26851) names the failure this avoids as
"not knowing": the generator lacks project-specific information about how to
build a dependency, so it fabricates something that cannot survive contact with
the code under test.

Only calls whose arguments are entirely literal are mined. A site like
`Team(id=db.next_id(), owner=current_user)` is unusable out of context — it
would drag in names the generated test cannot resolve — so it is skipped rather
than emitted and left to fail at Gate 4.

Follows invariant #6: returns empty on any error, never raises.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    "site-packages", ".tox", "build", "dist", ".mypy_cache",
}
_MAX_DEPTH = 12
_MAX_FILES = 2000


@dataclass(frozen=True)
class Construction:
    """A reusable way to build one type."""

    type_name: str
    module: str        # dotted module path the type lives in
    call_args: str     # argument text, e.g. 'id=1, owner_id=42'
    source: Path

    def expression(self) -> str:
        """A self-contained expression that constructs the object.

        Uses __import__ rather than a top-level import so the caller does not
        have to plumb import lines through the generators. sig_inspector
        already uses this idiom for datetime and re.
        """
        return (
            f"__import__({self.module!r}, fromlist=[{self.type_name!r}])"
            f".{self.type_name}({self.call_args})"
        )


def find_constructions(project_root: Path) -> dict[str, Construction]:
    """Return {type_name: Construction} mined from the project's own code."""
    try:
        return _find_cached(str(project_root.resolve()))
    except Exception:  # noqa: BLE001 — invariant #6
        return {}


@lru_cache(maxsize=32)
def _find_cached(root_str: str) -> dict[str, Construction]:
    root = Path(root_str)

    classes = _class_modules(root)
    if not classes:
        return {}

    found: dict[str, Construction] = {}
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name is None or name not in classes or name in found:
                continue
            args = _literal_args(node)
            if args is None:
                continue  # non-literal arguments — unusable out of context
            found[name] = Construction(
                type_name=name,
                module=classes[name],
                call_args=args,
                source=path,
            )

    return found


def resolve(annotation: str | None, constructions: dict[str, Construction]) -> str | None:
    """Return a construction expression for this annotation, or None."""
    if not annotation or not constructions:
        return None
    base = _base_type(annotation)
    found = constructions.get(base)
    return found.expression() if found else None


# ── internals ────────────────────────────────────────────────────────────────


def _py_files(root: Path) -> list[Path]:
    """Project .py files, pruning heavy directories in place.

    os.walk with in-place dirnames pruning rather than Path.rglob: rglob
    descends into every directory before filtering, so it walks .venv in full.
    That took the test suite from 68s to 683s when it shipped in #143's first
    draft — same mistake, same fix.
    """
    out: list[Path] = []
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        if len(Path(dirpath).parts) - root_depth > _MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath) / fn)
                if len(out) >= _MAX_FILES:
                    return out
    return out


def _class_modules(root: Path) -> dict[str, str]:
    """Map {ClassName: dotted.module.path} for classes defined in the project."""
    mapping: dict[str, str] = {}
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        module = _module_path(path, root)
        if not module:
            continue
        for node in tree.body:  # top-level classes only
            if isinstance(node, ast.ClassDef) and node.name not in mapping:
                mapping[node.name] = module
    return mapping


def _module_path(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return ""
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(p for p in parts if p)


def _literal_args(call: ast.Call) -> str | None:
    """Render a call's arguments if every one is a literal, else None."""
    if call.args and any(not _is_literal(a) for a in call.args):
        return None
    if any(not _is_literal(kw.value) for kw in call.keywords):
        return None
    if any(kw.arg is None for kw in call.keywords):  # **kwargs
        return None

    parts: list[str] = []
    try:
        parts.extend(ast.unparse(a) for a in call.args)
        parts.extend(f"{kw.arg}={ast.unparse(kw.value)}" for kw in call.keywords)
    except Exception:  # noqa: BLE001
        return None
    return ", ".join(parts)


def _is_literal(node: ast.expr) -> bool:
    """True for constants and containers built only from constants."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            k is not None and _is_literal(k) and _is_literal(v)
            for k, v in zip(node.keys, node.values)
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_literal(node.operand)
    return False


def _base_type(annotation: str) -> str:
    """'Optional[app.models.Team]' → 'Team'."""
    ann = annotation.strip()
    for wrapper in ("Optional[", "typing.Optional["):
        if ann.startswith(wrapper):
            ann = ann[len(wrapper):].rstrip("]")
            break
    ann = ann.split("|")[0].split(",")[0].strip().split("[")[0]
    return ann.split(".")[-1].strip()
