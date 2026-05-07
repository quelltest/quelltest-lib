"""
Tracks mutation score history in .quell/history.json.

Each entry is a snapshot of ProjectScore at a point in time.
Used by `quell score --compare` to show deltas between branches/runs.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from quell.score.calculator import ProjectScore


def record_score(
    score: ProjectScore,
    history_path: Path = Path(".quell/history.json"),
    label: str | None = None,
) -> None:
    """
    Append the current ProjectScore to the history file.

    Args:
        score: The project score to record.
        history_path: Path to the JSONL history file.
        label: Optional tag (e.g. git branch name or commit SHA).
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "label": label,
        "total_score": score.total_score,
        "percentage": score.percentage,
        "total_mutants": score.total_mutants,
        "killed_mutants": score.killed_mutants,
        "survived_mutants": score.survived_mutants,
        "files": [
            {
                "path": str(f.file_path),
                "score": f.quell_score,
                "total": f.total_mutants,
                "killed": f.killed_mutants,
                "survived": f.survived_mutants,
            }
            for f in score.files
        ],
    }

    existing: list[dict] = []
    if history_path.exists():
        try:
            existing = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    history_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def get_score_history(
    history_path: Path = Path(".quell/history.json"),
) -> list[dict]:
    """
    Load score history from the history file.

    Returns an empty list if the file does not exist or is malformed.
    """
    if not history_path.exists():
        return []
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def get_score_delta(
    current: ProjectScore,
    history_path: Path = Path(".quell/history.json"),
) -> float | None:
    """
    Return the score delta vs the last recorded run, or None if no history.
    Positive = improvement, negative = regression.
    """
    history = get_score_history(history_path)
    if not history:
        return None
    last = history[-1]
    return current.total_score - last.get("total_score", 0.0)
