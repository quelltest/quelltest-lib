"""
QuellGraph read-only query API.

All methods are pure reads against the SQLite graph.db produced by builder.py.
The caller holds a QuellGraph instance; the builder populates the database.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CallNode:
    """A node in the function call chain."""

    function_id: str
    name: str
    file: str
    is_resolved: bool
    infra_tags: list[str]


@dataclass(frozen=True)
class FunctionInfo:
    """Lightweight summary of a function from the graph."""

    id: str
    name: str
    file: str
    line_start: int
    docstring: str | None
    is_pure: bool
    purity_score: float
    annotation_coverage: float
    infra_tags: list[str]
    has_docstring: bool
    has_raises_block: bool
    has_returns_block: bool
    has_args_block: bool
    param_count: int


@dataclass(frozen=True)
class ClassInfo:
    """Lightweight summary of a class from the graph."""

    id: str
    name: str
    file: str
    is_pydantic: bool
    fields: list[dict]


class QuellGraph:
    """
    Read-only query interface to a QuellGraph SQLite database.

    Usage::

        graph = QuellGraph(Path(".quellgraph/graph.db"))
        tags  = graph.get_transitive_infra_tags(fn_id)
        graph.close()
    """

    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(
                f"QuellGraph database not found at {db_path}. "
                "Run `quell graph build` first."
            )
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Function lookups
    # ------------------------------------------------------------------

    def get_function(self, file: str, name: str) -> FunctionInfo | None:
        """Look up a function by file path and name."""
        row = self._conn.execute(
            "SELECT * FROM functions WHERE file=? AND name=? LIMIT 1",
            (file, name),
        ).fetchone()
        return _row_to_function(row) if row else None

    def get_function_by_id(self, function_id: str) -> FunctionInfo | None:
        """Look up a function by its graph ID."""
        row = self._conn.execute(
            "SELECT * FROM functions WHERE id=? LIMIT 1", (function_id,)
        ).fetchone()
        return _row_to_function(row) if row else None

    def list_functions(self, file: str | None = None) -> list[FunctionInfo]:
        """List all functions, optionally filtered by file."""
        if file:
            rows = self._conn.execute(
                "SELECT * FROM functions WHERE file=? ORDER BY line_start", (file,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM functions ORDER BY file, line_start"
            ).fetchall()
        return [_row_to_function(r) for r in rows]

    # ------------------------------------------------------------------
    # Infra tag queries
    # ------------------------------------------------------------------

    def get_transitive_infra_tags(self, function_id: str) -> set[str]:
        """Return all infra tags reachable from this function (BFS precomputed)."""
        row = self._conn.execute(
            "SELECT infra_tags FROM functions WHERE id=?", (function_id,)
        ).fetchone()
        if not row or not row["infra_tags"]:
            return set()
        return set(json.loads(row["infra_tags"]))

    def get_infra_dependency_path(self, function_id: str) -> list[str]:
        """
        Shortest path explaining WHY this function needs an infra tag.

        Returns a list of names: [caller, ..., callee, import, tag].
        Example: ["process_payment", "db.query", "Session", "sqlalchemy", "postgres"]
        """
        fn = self.get_function_by_id(function_id)
        if fn is None or not fn.infra_tags:
            return []

        path: list[str] = [fn.name]
        visited: set[str] = {function_id}
        queue = [function_id]

        while queue:
            current_id = queue.pop(0)
            # Find a callee that has infra tags
            for row in self._conn.execute(
                """SELECT c.callee_id, c.callee_name, f.infra_tags
                   FROM calls c
                   LEFT JOIN functions f ON f.id = c.callee_id
                   WHERE c.caller_id = ? AND c.is_resolved = 1""",
                (current_id,),
            ):
                if row["callee_id"] and row["callee_id"] not in visited:
                    callee_tags = json.loads(row["infra_tags"] or "[]")
                    path.append(row["callee_name"])
                    if callee_tags:
                        path.extend(callee_tags[:1])
                        return path
                    visited.add(row["callee_id"])
                    queue.append(row["callee_id"])

        # Fallback: show direct import tags
        module_row = self._conn.execute(
            "SELECT infra_tags FROM modules WHERE file=?", (fn.file,)
        ).fetchone()
        if module_row and module_row["infra_tags"]:
            tags = json.loads(module_row["infra_tags"])
            if tags:
                path.extend(tags[:1])
        return path

    # ------------------------------------------------------------------
    # Call chain queries
    # ------------------------------------------------------------------

    def get_call_chain(self, function_id: str, depth: int = 5) -> list[CallNode]:
        """Return the call tree up to `depth` levels deep (BFS)."""
        result: list[CallNode] = []
        visited: set[str] = {function_id}
        queue: list[tuple[str, int]] = [(function_id, 0)]

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for row in self._conn.execute(
                """SELECT c.callee_id, c.callee_name, c.is_resolved,
                          f.file, f.infra_tags
                   FROM calls c
                   LEFT JOIN functions f ON f.id = c.callee_id
                   WHERE c.caller_id = ?""",
                (current_id,),
            ):
                node = CallNode(
                    function_id=row["callee_id"] or "",
                    name=row["callee_name"],
                    file=row["file"] or "",
                    is_resolved=bool(row["is_resolved"]),
                    infra_tags=json.loads(row["infra_tags"] or "[]") if row["infra_tags"] else [],
                )
                result.append(node)
                if row["callee_id"] and row["callee_id"] not in visited:
                    visited.add(row["callee_id"])
                    queue.append((row["callee_id"], current_depth + 1))

        return result

    def has_cycles_in_chain(self, function_id: str) -> bool:
        """Return True if the call chain from this function contains a cycle."""
        visited: set[str] = set()
        stack: list[str] = [function_id]

        while stack:
            current = stack.pop()
            if current in visited:
                return True
            visited.add(current)
            for row in self._conn.execute(
                "SELECT callee_id FROM calls WHERE caller_id=? AND is_resolved=1",
                (current,),
            ):
                if row["callee_id"]:
                    stack.append(row["callee_id"])
        return False

    # ------------------------------------------------------------------
    # Pydantic model queries
    # ------------------------------------------------------------------

    def get_pydantic_models_used(self, function_id: str) -> list[ClassInfo]:
        """Pydantic model classes used as param or return types."""
        rows = self._conn.execute(
            """SELECT c.* FROM classes c
               JOIN uses_model um ON um.class_id = c.id
               WHERE um.function_id = ? AND c.is_pydantic = 1""",
            (function_id,),
        ).fetchall()
        return [_row_to_class(r) for r in rows]

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------

    def find_stale_tests(self, changed_files: list[str]) -> list[str]:
        """
        Given files changed since last `quell check`, return function IDs
        whose generated tests may now be stale.
        """
        stale: set[str] = set()
        for file in changed_files:
            # Functions defined in the changed file
            for row in self._conn.execute(
                "SELECT id FROM functions WHERE file=?", (file,)
            ):
                stale.add(row["id"])
            # Functions that call into this file (callers may be stale too)
            for row in self._conn.execute(
                """SELECT DISTINCT c.caller_id FROM calls c
                   JOIN functions f ON f.id = c.callee_id
                   WHERE f.file = ?""",
                (file,),
            ):
                stale.add(row["caller_id"])
        return list(stale)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return summary stats: function/class/infra/pure counts."""
        total_fns = self._conn.execute("SELECT COUNT(*) FROM functions").fetchone()[0]
        total_cls = self._conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        infra_fns = self._conn.execute(
            "SELECT COUNT(*) FROM functions WHERE infra_tags != '[]' AND infra_tags IS NOT NULL"
        ).fetchone()[0]
        pure_fns = self._conn.execute(
            "SELECT COUNT(*) FROM functions WHERE is_pure = 1"
        ).fetchone()[0]
        return {
            "functions": total_fns,
            "classes": total_cls,
            "infra_dependent": infra_fns,
            "pure": pure_fns,
        }


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _row_to_function(row: sqlite3.Row) -> FunctionInfo:
    return FunctionInfo(
        id=row["id"],
        name=row["name"],
        file=row["file"],
        line_start=row["line_start"] or 0,
        docstring=row["docstring"],
        is_pure=bool(row["is_pure"]),
        purity_score=row["purity_score"] or 0.0,
        annotation_coverage=row["annotation_coverage"] or 0.0,
        infra_tags=json.loads(row["infra_tags"] or "[]"),
        has_docstring=bool(row["has_docstring"]),
        has_raises_block=bool(row["has_raises_block"]),
        has_returns_block=bool(row["has_returns_block"]),
        has_args_block=bool(row["has_args_block"]),
        param_count=row["param_count"] or 0,
    )


def _row_to_class(row: sqlite3.Row) -> ClassInfo:
    return ClassInfo(
        id=row["id"],
        name=row["name"],
        file=row["file"],
        is_pydantic=bool(row["is_pydantic"]),
        fields=json.loads(row["fields"] or "[]"),
    )
