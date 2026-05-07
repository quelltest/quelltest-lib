"""Unit tests for MutmutAdapter."""
from __future__ import annotations
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from quell.adapters.mutmut_adapter import MutmutAdapter
from quell.core.models import MutantSource


SAMPLE_MUTMUT_RESULTS = """\
--- Survived ---
4, 5, 7-9
"""

SAMPLE_MUTMUT_SHOW = """\
--- src/calculator.py
+++ src/calculator.py
@@ -17,1 +17,1 @@
-    return age >= 18
+    return age > 18
"""


@pytest.fixture
def adapter(tmp_path: Path) -> MutmutAdapter:
    return MutmutAdapter(project_root=tmp_path)


def make_v3_cache(tmp_path: Path, rows: list[tuple] | None = None) -> Path:
    """Create a mutmut 3.x style .mutmut-cache SQLite file."""
    db = tmp_path / ".mutmut-cache"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE MutantStatus (id INTEGER PRIMARY KEY, source_path TEXT, status TEXT)"
    )
    if rows:
        conn.executemany("INSERT INTO MutantStatus VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def make_v2_cache(tmp_path: Path) -> Path:
    """Create a mutmut 2.x style .mutmut-cache with no MutantStatus table."""
    db = tmp_path / ".mutmut-cache"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE mutant (id INTEGER PRIMARY KEY, status TEXT)")
    conn.commit()
    conn.close()
    return db


class TestGetSurvivedIdsCli:
    """Tests for the v2 CLI fallback path."""

    def test_parses_single_ids(self, adapter: MutmutAdapter) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "--- Survived ---\n4, 5\n"
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            ids = adapter._get_survived_ids_cli()
        assert "4" in ids
        assert "5" in ids

    def test_parses_ranges(self, adapter: MutmutAdapter) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "--- Survived ---\n7-9\n"
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            ids = adapter._get_survived_ids_cli()
        assert "7" in ids
        assert "8" in ids
        assert "9" in ids

    def test_returns_empty_when_no_survivors(self, adapter: MutmutAdapter) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "--- Killed ---\n1, 2, 3\n"
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            ids = adapter._get_survived_ids_cli()
        assert ids == []

    def test_stops_at_killed_section(self, adapter: MutmutAdapter) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "--- Survived ---\n4, 5\n--- Killed ---\n6, 7\n"
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            ids = adapter._get_survived_ids_cli()
        assert "4" in ids
        assert "5" in ids
        assert "6" not in ids


class TestParseMutant:
    def test_parses_valid_diff(self, adapter: MutmutAdapter, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        calc = src_dir / "calculator.py"
        calc.write_text("x = 1\n")

        mock_result = MagicMock()
        mock_result.stdout = (
            "--- src/calculator.py\n"
            "+++ src/calculator.py\n"
            "@@ -17,1 +17,1 @@\n"
            "-    return age >= 18\n"
            "+    return age > 18\n"
        )
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            mutant = adapter._parse_mutant("42")

        assert mutant is not None
        assert mutant.id == "42"
        assert mutant.source == MutantSource.MUTMUT
        assert mutant.line_start == 17
        assert "age >= 18" in mutant.original_code
        assert "age > 18" in mutant.mutated_code

    def test_returns_none_for_unparseable_diff(self, adapter: MutmutAdapter) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "some garbage output"
        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=mock_result):
            mutant = adapter._parse_mutant("1")
        assert mutant is None


class TestReadSurvivors:
    def test_returns_empty_when_no_cache(self, adapter: MutmutAdapter) -> None:
        """No .mutmut-cache → returns [] with an error message."""
        mutants = adapter.read_survivors()
        assert mutants == []

    def test_returns_list_of_mutants_v2_fallback(
        self, adapter: MutmutAdapter, tmp_path: Path
    ) -> None:
        """v2 fallback path: no MutantStatus table → use CLI."""
        make_v2_cache(tmp_path)

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "calculator.py").write_text("x = 1\n")

        results_mock = MagicMock()
        results_mock.stdout = "--- Survived ---\n42\n"
        show_mock = MagicMock()
        show_mock.stdout = (
            "--- src/calculator.py\n"
            "+++ src/calculator.py\n"
            "@@ -17,1 +17,1 @@\n"
            "-    return age >= 18\n"
            "+    return age > 18\n"
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return results_mock if call_count == 1 else show_mock

        with patch("quell.adapters.mutmut_adapter.subprocess.run", side_effect=side_effect):
            mutants = adapter.read_survivors()

        assert len(mutants) == 1
        assert mutants[0].id == "42"

    def test_reads_survivors_from_v3_sqlite(
        self, adapter: MutmutAdapter, tmp_path: Path
    ) -> None:
        """v3 path: MutantStatus table exists → read IDs from SQLite, get diff via CLI."""
        make_v3_cache(tmp_path, rows=[(1, "src/calc.py", "survived")])

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "calc.py").write_text("x = 1\n")

        show_mock = MagicMock()
        show_mock.stdout = (
            "--- src/calc.py\n"
            "+++ src/calc.py\n"
            "@@ -5,1 +5,1 @@\n"
            "-    return x + 1\n"
            "+    return x - 1\n"
        )

        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=show_mock):
            mutants = adapter.read_survivors()

        assert len(mutants) == 1
        assert mutants[0].id == "1"
        assert mutants[0].source == MutantSource.MUTMUT

    def test_v3_ignores_non_survived_rows(
        self, adapter: MutmutAdapter, tmp_path: Path
    ) -> None:
        """Only survived mutants are returned from the v3 SQLite path."""
        make_v3_cache(tmp_path, rows=[
            (1, "src/a.py", "killed"),
            (2, "src/a.py", "survived"),
            (3, "src/a.py", "timeout"),
        ])

        show_mock = MagicMock()
        show_mock.stdout = (
            "--- src/a.py\n"
            "+++ src/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-    x = 1\n"
            "+    x = 2\n"
        )

        with patch("quell.adapters.mutmut_adapter.subprocess.run", return_value=show_mock):
            mutants = adapter.read_survivors()

        # Only id=2 has status=survived
        assert len(mutants) == 1
        assert mutants[0].id == "2"
