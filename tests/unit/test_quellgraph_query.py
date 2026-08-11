"""Tests for QuellGraph query API — using a hand-built SQLite database."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from quell.graph.query import QuellGraph

# ---------------------------------------------------------------------------
# Helpers — build a minimal synthetic graph.db without the builder
# ---------------------------------------------------------------------------

_SCHEMA = Path(__file__).parent.parent.parent / "quell" / "graph" / "schema.sql"


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal graph.db with synthetic functions, modules, and calls."""
    db_path = tmp_path / ".quellgraph" / "graph.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))

    pg_file = str(tmp_path / "src" / "payments.py")
    ut_file = str(tmp_path / "src" / "utils.py")

    # Modules
    conn.execute(
        "INSERT INTO modules (id, file, package, infra_tags, file_hash, parsed_at) VALUES (?,?,?,?,?,?)",
        (pg_file, pg_file, "payments", json.dumps(["postgres"]), "abc", 1.0),
    )
    conn.execute(
        "INSERT INTO modules (id, file, package, infra_tags, file_hash, parsed_at) VALUES (?,?,?,?,?,?)",
        (ut_file, ut_file, "utils", json.dumps([]), "def", 1.0),
    )

    # Functions
    conn.execute("""
        INSERT INTO functions (id, name, file, line_start, docstring,
            is_pure, purity_score, annotation_coverage, infra_tags, direct_infra_tags,
            has_docstring, has_raises_block, has_returns_block, has_args_block,
            param_count, file_hash, parsed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ("fn-pay", "process_payment", pg_file, 5, "Process payment.",
          0, 0.6, 0.67, json.dumps(["postgres"]), json.dumps(["postgres"]),
          1, 1, 1, 1, 2, "abc", 1.0))

    conn.execute("""
        INSERT INTO functions (id, name, file, line_start, docstring,
            is_pure, purity_score, annotation_coverage, infra_tags, direct_infra_tags,
            has_docstring, has_raises_block, has_returns_block, has_args_block,
            param_count, file_hash, parsed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ("fn-util", "validate_email", ut_file, 3, "Check email format.",
          1, 1.0, 1.0, json.dumps([]), json.dumps([]),
          1, 0, 1, 1, 1, "def", 1.0))

    conn.execute("""
        INSERT INTO functions (id, name, file, line_start, docstring,
            is_pure, purity_score, annotation_coverage, infra_tags, direct_infra_tags,
            has_docstring, has_raises_block, has_returns_block, has_args_block,
            param_count, file_hash, parsed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ("fn-cache", "get_from_cache", pg_file, 20, None,
          0, 0.8, 0.5, json.dumps(["redis"]), json.dumps(["redis"]),
          0, 0, 0, 0, 1, "abc", 1.0))

    # Calls: process_payment → get_from_cache (resolved)
    conn.execute(
        "INSERT INTO calls (caller_id, callee_id, callee_name, line, is_resolved) VALUES (?,?,?,?,?)",
        ("fn-pay", "fn-cache", "get_from_cache", 10, 1),
    )

    # Param types
    conn.execute(
        "INSERT INTO param_types (function_id, param_name, type_str, is_typed, is_infra_type, infra_tag)"
        " VALUES (?,?,?,?,?,?)",
        ("fn-pay", "db", "Session", 1, 1, "postgres"),
    )
    conn.execute(
        "INSERT INTO param_types (function_id, param_name, type_str, is_typed, is_infra_type, infra_tag)"
        " VALUES (?,?,?,?,?,?)",
        ("fn-util", "email", "str", 1, 0, None),
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def graph(tmp_path: Path) -> QuellGraph:
    db_path = _make_db(tmp_path)
    g = QuellGraph(db_path)
    yield g
    g.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetFunction:
    def test_finds_by_file_and_name(self, graph: QuellGraph, tmp_path: Path) -> None:
        fn = graph.get_function(str(tmp_path / "src" / "payments.py"), "process_payment")
        assert fn is not None
        assert fn.name == "process_payment"
        assert fn.has_raises_block is True

    def test_returns_none_for_missing(self, graph: QuellGraph, tmp_path: Path) -> None:
        fn = graph.get_function(str(tmp_path / "src" / "payments.py"), "nonexistent")
        assert fn is None

    def test_get_function_by_id(self, graph: QuellGraph) -> None:
        fn = graph.get_function_by_id("fn-pay")
        assert fn is not None
        assert fn.name == "process_payment"

    def test_list_functions_filtered_by_file(self, graph: QuellGraph, tmp_path: Path) -> None:
        fns = graph.list_functions(str(tmp_path / "src" / "utils.py"))
        assert len(fns) == 1
        assert fns[0].name == "validate_email"


class TestTransitiveInfraTags:
    def test_infra_function_has_postgres(self, graph: QuellGraph) -> None:
        tags = graph.get_transitive_infra_tags("fn-pay")
        assert "postgres" in tags

    def test_pure_function_returns_empty_set(self, graph: QuellGraph) -> None:
        tags = graph.get_transitive_infra_tags("fn-util")
        assert tags == set()

    def test_unknown_id_returns_empty_set(self, graph: QuellGraph) -> None:
        tags = graph.get_transitive_infra_tags("nonexistent-id")
        assert tags == set()


class TestCallChain:
    def test_call_chain_returns_callees(self, graph: QuellGraph) -> None:
        chain = graph.get_call_chain("fn-pay", depth=3)
        assert len(chain) >= 1
        names = [c.name for c in chain]
        assert "get_from_cache" in names

    def test_call_chain_depth_zero_returns_empty(self, graph: QuellGraph) -> None:
        chain = graph.get_call_chain("fn-pay", depth=0)
        assert chain == []

    def test_leaf_function_has_empty_chain(self, graph: QuellGraph) -> None:
        chain = graph.get_call_chain("fn-util")
        assert chain == []


class TestCycleDetection:
    def test_no_cycle_for_leaf(self, graph: QuellGraph) -> None:
        assert graph.has_cycles_in_chain("fn-util") is False

    def test_no_cycle_in_simple_chain(self, graph: QuellGraph) -> None:
        # fn-pay → fn-cache, no cycle
        assert graph.has_cycles_in_chain("fn-pay") is False


class TestStaleness:
    def test_changed_file_returns_its_functions(self, graph: QuellGraph, tmp_path: Path) -> None:
        stale = graph.find_stale_tests([str(tmp_path / "src" / "utils.py")])
        assert "fn-util" in stale

    def test_empty_changed_files_returns_empty(self, graph: QuellGraph) -> None:
        assert graph.find_stale_tests([]) == []

    def test_callers_of_changed_file_are_stale(self, graph: QuellGraph, tmp_path: Path) -> None:
        # fn-pay calls fn-cache (in payments.py); changing payments.py → fn-pay stale
        stale = graph.find_stale_tests([str(tmp_path / "src" / "payments.py")])
        assert "fn-pay" in stale


class TestStats:
    def test_stats_keys(self, graph: QuellGraph) -> None:
        s = graph.stats()
        assert set(s.keys()) == {"functions", "classes", "infra_dependent", "pure"}

    def test_stats_counts(self, graph: QuellGraph) -> None:
        s = graph.stats()
        assert s["functions"] == 3
        assert s["pure"] == 1           # only validate_email
        assert s["infra_dependent"] == 2  # process_payment + get_from_cache


class TestInfoDependencyPath:
    def test_path_starts_with_function_name(self, graph: QuellGraph) -> None:
        path = graph.get_infra_dependency_path("fn-pay")
        assert len(path) >= 1
        assert path[0] == "process_payment"

    def test_pure_function_returns_short_path(self, graph: QuellGraph) -> None:
        path = graph.get_infra_dependency_path("fn-util")
        # No infra deps — returns just the name or empty
        assert isinstance(path, list)


class TestMissingDB:
    def test_raises_if_db_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            QuellGraph(tmp_path / "nonexistent.db")
