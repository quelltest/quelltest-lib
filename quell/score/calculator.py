"""
Calculates Quell Score — mutation-verified coverage per file and project.

Quell Score = killed_mutants / total_mutants (per file or project-wide).

This is a stronger metric than line coverage because it requires tests to
actually catch behavioral changes, not just execute lines.
"""
from __future__ import annotations
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileScore:
    """Mutation score for a single source file."""

    file_path: Path
    total_mutants: int
    killed_mutants: int
    survived_mutants: int
    quell_score: float  # 0.0 to 1.0

    @property
    def percentage(self) -> int:
        """Score as integer percentage (0-100)."""
        return int(self.quell_score * 100)

    @property
    def grade(self) -> str:
        """Letter grade: A ≥80%, B ≥60%, C ≥40%, F otherwise."""
        if self.quell_score >= 0.80:
            return "A"
        if self.quell_score >= 0.60:
            return "B"
        if self.quell_score >= 0.40:
            return "C"
        return "F"


@dataclass
class ProjectScore:
    """Aggregate mutation score across all files."""

    files: list[FileScore] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        """Weighted score across all files (0.0 to 1.0)."""
        if not self.files:
            return 0.0
        total = sum(f.total_mutants for f in self.files)
        if total == 0:
            return 0.0
        killed = sum(f.killed_mutants for f in self.files)
        return killed / total

    @property
    def percentage(self) -> int:
        """Project score as integer percentage."""
        return int(self.total_score * 100)

    @property
    def total_mutants(self) -> int:
        return sum(f.total_mutants for f in self.files)

    @property
    def killed_mutants(self) -> int:
        return sum(f.killed_mutants for f in self.files)

    @property
    def survived_mutants(self) -> int:
        return sum(f.survived_mutants for f in self.files)


def calculate_score(project_root: Path = Path(".")) -> ProjectScore:
    """
    Read the mutmut cache and calculate mutation scores per file.

    Inspects the SQLite schema at runtime to handle different mutmut versions.

    Raises:
        FileNotFoundError: if .mutmut-cache does not exist.
        ValueError: if the cache schema is unrecognized.
    """
    db = project_root / ".mutmut-cache"
    if not db.exists():
        raise FileNotFoundError(
            "No mutation testing results found.\n\n"
            "Run mutation testing first:\n"
            "  mutmut run\n\n"
            "Then run: quell score"
        )

    conn = sqlite3.connect(db)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        if "MutantStatus" in table_names:
            return _calculate_from_mutmut3(conn)

        raise ValueError(
            f"Unrecognized .mutmut-cache schema. Tables found: {sorted(table_names)}\n"
            "Only mutmut 3.x is supported. Upgrade: pip install mutmut>=3.5.0"
        )
    finally:
        conn.close()


def _calculate_from_mutmut3(conn: sqlite3.Connection) -> ProjectScore:
    """Parse mutmut 3.x MutantStatus schema into a ProjectScore."""
    cols = conn.execute("PRAGMA table_info(MutantStatus)").fetchall()
    col_names = [c[1] for c in cols]

    rows = conn.execute("SELECT * FROM MutantStatus").fetchall()

    by_file: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "killed": 0, "survived": 0}
    )

    for row in rows:
        row_dict = dict(zip(col_names, row))
        source = str(row_dict.get("source_path") or row_dict.get("file") or "unknown")
        status = str(row_dict.get("status", "")).lower()

        by_file[source]["total"] += 1
        if "killed" in status or "timeout" in status:
            by_file[source]["killed"] += 1
        elif "survived" in status:
            by_file[source]["survived"] += 1

    files = []
    for path_str, counts in by_file.items():
        total = counts["total"]
        killed = counts["killed"]
        files.append(FileScore(
            file_path=Path(path_str),
            total_mutants=total,
            killed_mutants=killed,
            survived_mutants=counts["survived"],
            quell_score=killed / total if total > 0 else 0.0,
        ))

    return ProjectScore(files=sorted(files, key=lambda f: f.quell_score))
