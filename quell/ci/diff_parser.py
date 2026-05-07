"""
Parses git diff output to extract changed line ranges per file.

Used by `quell ci --diff-only` to restrict mutation testing to only the
lines changed in the current branch vs base (e.g. origin/main).

This makes Quell viable in every PR pipeline: instead of mutating the full
project (15-30 min), we only mutate changed lines (2-3 min).
"""
from __future__ import annotations
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChangedLines:
    """Changed line ranges for a single file."""

    file_path: Path
    line_ranges: list[tuple[int, int]] = field(default_factory=list)  # [(start, end), ...]

    def contains_line(self, line: int) -> bool:
        """Return True if the given line number falls within any changed range."""
        return any(start <= line <= end for start, end in self.line_ranges)


def get_changed_lines(
    base_ref: str = "origin/main",
    project_root: Path = Path("."),
) -> list[ChangedLines]:
    """
    Run `git diff --unified=0 <base_ref>...HEAD` and return which lines changed.

    Returns one ChangedLines per modified Python file. Returns an empty list
    if not in a git repo or if there are no Python file changes.

    Args:
        base_ref: The git ref to compare against (default: origin/main).
        project_root: Directory to run git from.
    """
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    if result.returncode != 0:
        # Try HEAD~1 fallback for repos without a remote
        result = subprocess.run(
            ["git", "diff", "--unified=0", "HEAD~1...HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )

    if result.returncode != 0 or not result.stdout:
        return []

    return _parse_unified_diff(result.stdout, project_root)


def _parse_unified_diff(diff_output: str, root: Path) -> list[ChangedLines]:
    """
    Parse unified diff format into per-file changed line ranges.

    Unified diff hunk header format:
        @@ -old_start,old_count +new_start,new_count @@
    We care only about the new file (+) line numbers.
    """
    result: list[ChangedLines] = []
    current_file: str | None = None
    current_ranges: list[tuple[int, int]] = []

    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            if current_file is not None and current_ranges:
                result.append(ChangedLines(
                    file_path=root / current_file,
                    line_ranges=current_ranges,
                ))
            current_file = line[6:]   # strip "+++ b/"
            current_ranges = []

        elif line.startswith("@@") and current_file is not None:
            # @@ -old +new,count @@
            match = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or "1")
                if count > 0:
                    current_ranges.append((start, start + count - 1))

    if current_file is not None and current_ranges:
        result.append(ChangedLines(
            file_path=root / current_file,
            line_ranges=current_ranges,
        ))

    # Only Python files are relevant for mutation testing
    return [c for c in result if c.file_path.suffix == ".py"]
