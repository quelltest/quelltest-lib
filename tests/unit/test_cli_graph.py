"""
Unit tests for quell graph subcommands and quell teardown.

Uses typer's CliRunner for CLI invocation and hand-built SQLite databases
so tests have no dependency on the builder.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from quell.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal quellgraph db with one function."""
    graph_dir = tmp_path / ".quellgraph"
    graph_dir.mkdir()
    db_path = graph_dir / "graph.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS graph_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS functions (
            id                   TEXT PRIMARY KEY,
            name                 TEXT NOT NULL,
            file                 TEXT NOT NULL,
            line_start           INTEGER DEFAULT 0,
            line_end             INTEGER DEFAULT 0,
            docstring            TEXT,
            is_async             INTEGER DEFAULT 0,
            is_method            INTEGER DEFAULT 0,
            is_pure              INTEGER DEFAULT 1,
            purity_score         REAL DEFAULT 1.0,
            annotation_coverage  REAL DEFAULT 0.0,
            infra_tags           TEXT DEFAULT '[]',
            has_docstring        INTEGER DEFAULT 0,
            has_raises_block     INTEGER DEFAULT 0,
            has_returns_block    INTEGER DEFAULT 0,
            has_args_block       INTEGER DEFAULT 0,
            param_count          INTEGER DEFAULT 0,
            file_hash            TEXT,
            parsed_at            REAL
        );
        CREATE TABLE IF NOT EXISTS classes (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            file         TEXT NOT NULL,
            line_start   INTEGER DEFAULT 0,
            line_end     INTEGER DEFAULT 0,
            bases        TEXT DEFAULT '[]',
            is_pydantic  INTEGER DEFAULT 0,
            is_dataclass INTEGER DEFAULT 0,
            fields       TEXT DEFAULT '[]',
            file_hash    TEXT,
            parsed_at    REAL
        );
        CREATE TABLE IF NOT EXISTS modules (
            file       TEXT PRIMARY KEY,
            infra_tags TEXT DEFAULT '[]',
            file_hash  TEXT,
            parsed_at  REAL
        );
        CREATE TABLE IF NOT EXISTS calls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_id   TEXT,
            callee_id   TEXT,
            callee_name TEXT,
            line        INTEGER DEFAULT 0,
            is_resolved INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS param_types (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            function_id   TEXT,
            param_name    TEXT,
            type_str      TEXT,
            is_typed      INTEGER DEFAULT 0,
            is_infra_type INTEGER DEFAULT 0,
            infra_tag     TEXT
        );
        CREATE TABLE IF NOT EXISTS imports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            file       TEXT,
            package    TEXT,
            infra_tag  TEXT
        );
        CREATE TABLE IF NOT EXISTS inherits (
            class_id  TEXT,
            base_name TEXT
        );
        CREATE TABLE IF NOT EXISTS uses_model (
            function_id TEXT,
            class_id    TEXT
        );
        INSERT INTO graph_meta VALUES ('schema_version', '1');
        INSERT INTO functions VALUES (
            'fn-abc', 'my_func', 'src/app.py', 10, 20,
            'Does something.', 0, 0, 1, 1.0, 0.8,
            '["postgres"]', 1, 1, 1, 1, 3, 'hash1', 1.0
        );
    """)
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# quell graph build
# ---------------------------------------------------------------------------


class TestGraphBuild:
    def test_build_on_empty_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        result = runner.invoke(app, ["graph", "build", str(src), "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "QuellGraph built" in result.output

    def test_build_creates_db(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "sample.py").write_text("def foo(): pass\n")
        runner.invoke(app, ["graph", "build", str(src), "--root", str(tmp_path)])
        db = tmp_path / ".quellgraph" / "graph.db"
        assert db.exists()


# ---------------------------------------------------------------------------
# quell graph show
# ---------------------------------------------------------------------------


class TestGraphShow:
    def test_show_lists_function(self, tmp_path):
        _make_db(tmp_path)
        result = runner.invoke(app, ["graph", "show", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "my_func" in result.output

    def test_show_no_graph_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "show", "--root", str(tmp_path)])
        assert result.exit_code == 1
        assert "quell graph build" in result.output


# ---------------------------------------------------------------------------
# quell graph why
# ---------------------------------------------------------------------------


class TestGraphWhy:
    def test_why_known_function(self, tmp_path):
        _make_db(tmp_path)
        result = runner.invoke(app, ["graph", "why", "my_func", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "my_func" in result.output

    def test_why_unknown_function_exits_1(self, tmp_path):
        _make_db(tmp_path)
        result = runner.invoke(app, ["graph", "why", "nonexistent_fn", "--root", str(tmp_path)])
        assert result.exit_code == 1

    def test_why_no_graph_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "why", "my_func", "--root", str(tmp_path)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# quell graph stale
# ---------------------------------------------------------------------------


class TestGraphStale:
    def test_stale_no_graph_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "stale", "--root", str(tmp_path)])
        assert result.exit_code == 1

    def test_stale_with_graph_runs(self, tmp_path):
        _make_db(tmp_path)
        result = runner.invoke(app, ["graph", "stale", "--root", str(tmp_path)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# quell graph stats
# ---------------------------------------------------------------------------


class TestGraphStats:
    def test_stats_no_graph_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "stats", "--root", str(tmp_path)])
        assert result.exit_code == 1

    def test_stats_shows_counts(self, tmp_path):
        _make_db(tmp_path)
        result = runner.invoke(app, ["graph", "stats", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "Total functions" in result.output


# ---------------------------------------------------------------------------
# quell teardown
# ---------------------------------------------------------------------------


class TestTeardown:
    def test_teardown_no_containers(self, tmp_path):
        result = runner.invoke(app, ["teardown", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "No running" in result.output

    def test_teardown_with_mock_containers(self, tmp_path):
        from unittest.mock import patch
        with patch("quell.infra.engine.ContainerEngine.teardown", return_value=["redis", "postgres"]):
            result = runner.invoke(app, ["teardown", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "redis" in result.output or "postgres" in result.output


# ---------------------------------------------------------------------------
# quell check new flags (smoke tests — no real containers)
# ---------------------------------------------------------------------------


class TestCheckNewFlags:
    def test_check_accepts_min_confidence(self, tmp_path):
        # Should not error on unrecognized option
        (tmp_path / "src").mkdir()
        result = runner.invoke(app, [
            "check", str(tmp_path / "src"),
            "--min-confidence", "70",
            "--root", str(tmp_path),
        ])
        # Not checking exit code (SDK may fail without config) — just no OptionError
        assert "--min-confidence" not in result.output or "No such option" not in result.output

    def test_check_accepts_graph_rebuild_flag(self, tmp_path):
        (tmp_path / "src").mkdir()
        result = runner.invoke(app, [
            "check", str(tmp_path / "src"),
            "--graph-rebuild",
            "--root", str(tmp_path),
        ])
        assert "No such option" not in result.output

    def test_check_accepts_keep_containers_flag(self, tmp_path):
        (tmp_path / "src").mkdir()
        result = runner.invoke(app, [
            "check", str(tmp_path / "src"),
            "--keep-containers",
            "--root", str(tmp_path),
        ])
        assert "No such option" not in result.output
