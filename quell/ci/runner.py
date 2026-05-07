"""
Runs mutmut programmatically for Quell CI mode.

Supports two modes:
  - Full run: mutates entire project (accurate but slow, 15-30 min on large projects)
  - Targeted run: mutates only files/modules containing changed lines (2-3 min for PRs)

The targeted run is the killer feature that makes Quell viable in every PR pipeline.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

from quell.ci.diff_parser import ChangedLines


def run_mutmut_full(project_root: Path = Path(".")) -> int:
    """
    Run full mutation testing via `mutmut run`.

    Shows progress output to the user (capture_output=False).
    Returns the mutmut exit code (0 = success, 1 = survivors found).
    """
    result = subprocess.run(
        ["mutmut", "run"],
        cwd=project_root,
    )
    return result.returncode


def run_mutmut_targeted(
    changed: list[ChangedLines],
    project_root: Path = Path("."),
) -> int:
    """
    Run mutation testing only on modules containing changed lines.

    mutmut 3.x accepts module path patterns like `src.payments` to restrict
    which code gets mutated. This avoids the full project scan and keeps
    CI runtime under 3 minutes for typical PRs.

    Args:
        changed: List of ChangedLines from diff_parser.get_changed_lines().
        project_root: Project root directory.

    Returns:
        mutmut exit code.
    """
    modules = []
    for change in changed:
        module_path = _file_to_module(change.file_path, project_root)
        if module_path:
            modules.append(module_path)

    if not modules:
        return 0  # nothing to mutate

    result = subprocess.run(
        ["mutmut", "run"] + modules,
        cwd=project_root,
    )
    return result.returncode


def _file_to_module(file_path: Path, project_root: Path) -> str | None:
    """
    Convert a file path to a dotted module path.

    Example: project_root/src/payments.py → src.payments
    Returns None if the file is outside the project root.
    """
    try:
        rel = file_path.relative_to(project_root)
        return str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")
    except ValueError:
        return None
