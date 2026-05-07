"""
Reads surviving mutants from mutmut's SQLite cache.

Supports mutmut 3.x (queries .mutmut-cache SQLite DB directly) with a
CLI-based fallback for mutmut 2.x compatibility.

mutmut 3.x notes:
  - Fork-based execution model (not subprocess-per-mutant)
  - Results stored in .mutmut-cache (SQLite), table: MutantStatus
  - `mutmut apply <id>` and `mutmut show <id>` still work
  - Does NOT run on Windows without WSL
"""
from __future__ import annotations
import sqlite3
import subprocess
import re
from pathlib import Path
from quell.core.models import SurvivedMutant, MutantSource
from quell.adapters.base import MutationAdapter


class MutmutAdapter(MutationAdapter):
    """
    Reads survived mutants from mutmut.

    Detects mutmut 2.x vs 3.x automatically by inspecting the SQLite schema.
    mutmut 3.x: queries MutantStatus table directly (more reliable than CLI parsing).
    mutmut 2.x: falls back to `mutmut results` + `mutmut show` CLI approach.

    Requires mutmut to be installed and `mutmut run` to have been executed.
    On Windows, mutmut 3.x requires WSL.
    """

    def __init__(self, project_root: Path = Path(".")):
        self.project_root = project_root
        self._db_path = project_root / ".mutmut-cache"

    def read_survivors(self) -> list[SurvivedMutant]:
        """Parse mutmut results and return all survived mutants."""
        if not self._db_path.exists():
            from rich.panel import Panel
            from rich.console import Console
            Console().print(Panel(
                "[red]Error:[/red] No mutation testing results found.\n\n"
                "Quell needs mutation testing results to work.\n"
                "Run mutation testing first:\n\n"
                "  [bold]mutmut run[/bold]\n\n"
                "Then run Quell again.",
                title="Quell",
                border_style="red",
            ))
            return []

        if self._is_mutmut3():
            return self._read_survivors_v3()
        return self._read_survivors_v2()

    def _is_mutmut3(self) -> bool:
        """Check if the cache is from mutmut 3.x by inspecting the schema."""
        try:
            conn = sqlite3.connect(self._db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            conn.close()
            table_names = {t[0] for t in tables}
            return "MutantStatus" in table_names
        except sqlite3.DatabaseError:
            return False

    def _read_survivors_v3(self) -> list[SurvivedMutant]:
        """Read survivors using mutmut 3.x SQLite schema."""
        conn = sqlite3.connect(self._db_path)
        try:
            # Inspect actual columns to handle minor schema variations across 3.x releases
            cols = conn.execute("PRAGMA table_info(MutantStatus)").fetchall()
            col_names = [c[1] for c in cols]

            rows = conn.execute(
                "SELECT * FROM MutantStatus WHERE status = 'survived'"
            ).fetchall()
        finally:
            conn.close()

        mutants = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            mutant_id = str(row_dict.get("id", ""))

            # Use `mutmut show <id>` to get the diff — more reliable than
            # reconstructing it from the mutation column alone.
            mutant = self._parse_mutant(mutant_id)
            if mutant:
                mutants.append(mutant)

        return mutants

    def _read_survivors_v2(self) -> list[SurvivedMutant]:
        """Read survivors using mutmut 2.x CLI approach."""
        survived_ids = self._get_survived_ids_cli()
        mutants = []
        for mutant_id in survived_ids:
            mutant = self._parse_mutant(mutant_id)
            if mutant:
                mutants.append(mutant)
        return mutants

    def _get_survived_ids_cli(self) -> list[str]:
        """Run `mutmut results` and extract IDs of survived mutants (v2.x)."""
        result = subprocess.run(
            ["mutmut", "results"],
            capture_output=True,
            text=True,
            cwd=self.project_root,
        )
        ids = []
        in_survived = False
        for line in result.stdout.splitlines():
            if "Survived" in line:
                in_survived = True
                continue
            if in_survived:
                if line.strip().startswith("----"):
                    continue
                if line.strip() == "" or ("Killed" in line or "Timeout" in line):
                    break
                parts = re.findall(r'\d+(?:-\d+)?', line)
                for part in parts:
                    if "-" in part:
                        start, end = part.split("-")
                        ids.extend(str(i) for i in range(int(start), int(end) + 1))
                    else:
                        ids.append(part)
        return ids

    def _parse_mutant(self, mutant_id: str) -> SurvivedMutant | None:
        """Run `mutmut show <id>` and parse the unified diff output."""
        result = subprocess.run(
            ["mutmut", "show", mutant_id],
            capture_output=True,
            text=True,
            cwd=self.project_root,
        )
        output = result.stdout

        file_match = re.search(r'^--- (.+)$', output, re.MULTILINE)
        line_match = re.search(r'^@@ -(\d+)', output, re.MULTILINE)
        original_match = re.search(r'^- (.+)$', output, re.MULTILINE)
        mutated_match = re.search(r'^\+ (.+)$', output, re.MULTILINE)

        if not all([file_match, line_match, original_match, mutated_match]):
            return None

        file_path = self.project_root / file_match.group(1).strip()

        return SurvivedMutant(
            id=mutant_id,
            source=MutantSource.MUTMUT,
            file_path=file_path.resolve(),
            line_start=int(line_match.group(1)),
            line_end=int(line_match.group(1)),
            original_code=original_match.group(1),
            mutated_code=mutated_match.group(1),
        )
