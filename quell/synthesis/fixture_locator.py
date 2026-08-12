"""
Discovers the project's own pytest fixtures so generated tests can reuse them
instead of guessing literal stub values.  (spec10 §4.4, issue #143)

Why this exists
---------------
`sig_inspector._stub_param` falls back to the literal `None` for any type it
does not recognise.  On a project built around async SQLAlchemy that turns

    async def add_member(db: AsyncSession, team: Team, user_id: int)

into `add_member(db=None, team=None, user_id=1)`.  The guard `if not
team.owner_id:` then raises AttributeError on NoneType rather than the intended
error, Gate 4 rejects the test, and `--fix` reports 0-for-0.

The evaluated backend already defined a `db_session` fixture in its conftest.
We never looked.  This module looks.

Resolution is name-first, then type: a fixture literally called `db_session`
matching a parameter called `db_session` is a stronger signal than a return
annotation match, because fixture return types are frequently unannotated.

Follows invariant #6 — every reader returns empty on any error, never raises.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "site-packages", ".tox"}

# Fixtures pytest provides itself. Never treat these as project fixtures — they
# are always available and must not be shadowed by a same-named conftest lookup.
BUILTIN_FIXTURES = frozenset({
    "tmp_path", "tmp_path_factory", "capsys", "capfd", "monkeypatch",
    "request", "caplog", "recwarn", "pytestconfig", "cache", "doctest_namespace",
})


@dataclass(frozen=True)
class FixtureInfo:
    """One pytest fixture discovered in a project conftest."""

    name: str
    return_annotation: str | None
    file: Path
    is_async: bool = False

    @property
    def yields(self) -> bool:
        """Generator fixtures are fine to request; the distinction is for docs."""
        return False


def find_fixtures(project_root: Path) -> dict[str, FixtureInfo]:
    """Return {fixture_name: FixtureInfo} for every conftest.py under the root.

    Nearest-to-root wins on duplicate names, which is not pytest's real
    resolution order (pytest prefers the conftest closest to the *test*). That
    is acceptable here because we only need to know a fixture by that name
    exists and is requestable; pytest performs the real binding at run time.
    """
    try:
        return _find_fixtures_cached(str(project_root.resolve()))
    except Exception:  # noqa: BLE001 — invariant #6: readers never raise
        return {}


@lru_cache(maxsize=32)
def _find_fixtures_cached(root_str: str) -> dict[str, FixtureInfo]:
    root = Path(root_str)
    found: dict[str, FixtureInfo] = {}

    # os.walk with in-place pruning, NOT Path.rglob. rglob descends into every
    # directory and only then lets us filter, so it walks .venv and
    # node_modules in full — on this repo that turned a 68s test suite into
    # 683s. Pruning topdown skips those subtrees entirely.
    for conftest in sorted(_walk_conftests(root), key=lambda p: len(p.parts)):
        try:
            tree = ast.parse(conftest.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_fixture(node):
                continue
            if node.name in found or node.name in BUILTIN_FIXTURES:
                continue
            found[node.name] = FixtureInfo(
                name=node.name,
                return_annotation=_ann(node.returns),
                file=conftest,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )

    return found


def resolve(
    param_name: str,
    annotation: str | None,
    fixtures: dict[str, FixtureInfo],
) -> str | None:
    """Return the name of a fixture satisfying this parameter, or None.

    Order is deliberate:
      1. exact name match      — `db_session` param ← `db_session` fixture
      2. name contained in a fixture name, or vice versa — `db` ← `db_session`
      3. return-annotation type match — any fixture annotated `-> AsyncSession`

    Type match is last because fixture return types are commonly unannotated,
    so a hit there is rarer but not stronger.
    """
    if not fixtures or not param_name:
        return None

    if param_name in fixtures:
        return param_name

    lowered = param_name.lower()
    if len(lowered) >= 2:
        for name in fixtures:
            low = name.lower()
            if low == lowered or low.startswith(f"{lowered}_") or low.endswith(f"_{lowered}"):
                return name

    if annotation:
        base = _base_type(annotation)
        if base:
            for name, info in fixtures.items():
                if info.return_annotation and _base_type(info.return_annotation) == base:
                    return name

    return None


# ── internals ────────────────────────────────────────────────────────────────

# Depth cap relative to the project root. A conftest fifteen levels down is not
# this project's test configuration; it belongs to something vendored.
_MAX_DEPTH = 6


def _walk_conftests(root: Path) -> list[Path]:
    """Find conftest.py files, pruning heavy and irrelevant subtrees."""
    import os

    out: list[Path] = []
    root_depth = len(root.parts)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        # In-place mutation is what makes os.walk skip these subtrees.
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        if len(current.parts) - root_depth >= _MAX_DEPTH:
            dirnames[:] = []
            continue
        if "conftest.py" in filenames:
            out.append(current / "conftest.py")

    return out


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if decorated with @pytest.fixture / @fixture, with or without call."""
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        name = (
            target.attr if isinstance(target, ast.Attribute)
            else target.id if isinstance(target, ast.Name)
            else ""
        )
        if name == "fixture":
            return True
    return False


def _ann(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return None


def _base_type(annotation: str) -> str:
    """Strip generics, module paths and Optional wrappers → bare type name.

    'Optional[sqlalchemy.ext.asyncio.AsyncSession]' → 'AsyncSession'
    """
    ann = annotation.strip()
    for wrapper in ("Optional[", "typing.Optional[", "AsyncGenerator[", "Generator[", "Iterator["):
        if ann.startswith(wrapper):
            ann = ann[len(wrapper):].rstrip("]")
            break
    ann = ann.split(",")[0].split("|")[0].strip()
    ann = ann.split("[")[0]
    return ann.split(".")[-1].strip()
