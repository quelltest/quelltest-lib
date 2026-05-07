"""Tests for quell/score/calculator.py"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from quell.score.calculator import (
    FileScore,
    ProjectScore,
    _calculate_from_mutmut3,
    calculate_score,
)


def make_mutmut3_db(rows: list[tuple]) -> Path:
    """
    Create a temporary .mutmut-cache SQLite file with the mutmut 3.x schema.
    rows: list of (id, source_path, status) tuples.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE MutantStatus (id INTEGER PRIMARY KEY, source_path TEXT, status TEXT)"
    )
    conn.executemany("INSERT INTO MutantStatus VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db_path


def test_calculate_from_mutmut3_basic():
    db_path = make_mutmut3_db([
        (1, "src/calc.py", "killed"),
        (2, "src/calc.py", "survived"),
        (3, "src/calc.py", "killed"),
        (4, "src/utils.py", "survived"),
    ])
    conn = sqlite3.connect(db_path)
    score = _calculate_from_mutmut3(conn)
    conn.close()
    db_path.unlink()

    assert score.total_mutants == 4
    assert score.killed_mutants == 2
    assert score.survived_mutants == 2

    calc = next(f for f in score.files if "calc.py" in str(f.file_path))
    assert calc.total_mutants == 3
    assert calc.killed_mutants == 2
    assert calc.survived_mutants == 1
    assert pytest.approx(calc.quell_score, abs=0.01) == 2 / 3


def test_calculate_from_mutmut3_timeout_counts_as_killed():
    db_path = make_mutmut3_db([
        (1, "src/x.py", "timeout"),
        (2, "src/x.py", "survived"),
    ])
    conn = sqlite3.connect(db_path)
    score = _calculate_from_mutmut3(conn)
    conn.close()
    db_path.unlink()

    assert score.killed_mutants == 1  # timeout counts as killed
    assert score.survived_mutants == 1


def test_project_score_total_score_weighted():
    files = [
        FileScore(
            file_path=Path("a.py"),
            total_mutants=10,
            killed_mutants=8,
            survived_mutants=2,
            quell_score=0.8,
        ),
        FileScore(
            file_path=Path("b.py"),
            total_mutants=2,
            killed_mutants=1,
            survived_mutants=1,
            quell_score=0.5,
        ),
    ]
    project = ProjectScore(files=files)
    # weighted: (8+1)/(10+2) = 9/12 = 0.75
    assert pytest.approx(project.total_score, abs=0.001) == 9 / 12
    assert project.percentage == 75


def test_project_score_empty():
    project = ProjectScore()
    assert project.total_score == 0.0
    assert project.percentage == 0


def test_file_score_grade():
    def make(score: float) -> FileScore:
        return FileScore(
            file_path=Path("x.py"),
            total_mutants=10,
            killed_mutants=int(score * 10),
            survived_mutants=10 - int(score * 10),
            quell_score=score,
        )

    assert make(0.85).grade == "A"
    assert make(0.65).grade == "B"
    assert make(0.45).grade == "C"
    assert make(0.30).grade == "F"


def test_calculate_score_no_cache(tmp_path):
    with pytest.raises(FileNotFoundError):
        calculate_score(tmp_path)


def test_calculate_score_unknown_schema(tmp_path):
    db = tmp_path / ".mutmut-cache"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE SomeOtherTable (id INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Unrecognized"):
        calculate_score(tmp_path)


def test_calculate_score_full_flow(tmp_path):
    db = tmp_path / ".mutmut-cache"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE MutantStatus (id INTEGER PRIMARY KEY, source_path TEXT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO MutantStatus VALUES (?, ?, ?)",
        [
            (1, "src/app.py", "killed"),
            (2, "src/app.py", "killed"),
            (3, "src/app.py", "survived"),
        ],
    )
    conn.commit()
    conn.close()

    score = calculate_score(tmp_path)
    assert score.percentage == 66  # int(2/3 * 100)
    assert len(score.files) == 1
