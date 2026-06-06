"""Build the privacy-preserving sync payload from a local report.json.

Never raises — returns None on any error so a failed payload build never
blocks a `quell find` run.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

from quell import __version__
from quell.sync.models import (
    EdgeCaseCounts,
    FlaggedMeta,
    ScaffoldedMeta,
    SyncPayload,
    WrittenTestMeta,
)

_SYNC_HISTORY = Path(".quell/sync_history.json")


def _project_id(project_root: Path) -> str:
    """Derive a stable project ID from the git remote URL, or cwd as fallback."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=5,
        )
        if result.returncode == 0:
            remote = result.stdout.strip()
            return hashlib.sha256(remote.encode()).hexdigest()
    except Exception:  # noqa: BLE001
        pass
    return hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()


def _last_prs(project_id: str) -> int | None:
    """Read the most recent PRS from sync history, or None if no history."""
    try:
        if _SYNC_HISTORY.exists():
            history = json.loads(_SYNC_HISTORY.read_text())
            entries = [e for e in history if e.get("project_id") == project_id]
            if entries:
                return entries[-1]["prs"]
    except Exception:  # noqa: BLE001
        pass
    return None


def build_sync_payload(
    report_path: Path,
    project_root: Path = Path("."),
    project_alias: str = "",
) -> SyncPayload | None:
    """Convert .quell/report.json into a safe SyncPayload.

    Returns None if the report is missing or malformed — never raises.
    No source code, docstrings, test bodies, or variable names are included.
    """
    try:
        if not report_path.exists():
            return None
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    try:
        pid = _project_id(project_root)
        summary = raw.get("summary", {})
        prs = int(summary.get("prs_score", 0))
        previous_prs = _last_prs(pid)
        prs_delta = (prs - previous_prs) if previous_prs is not None else 0

        alias = project_alias or raw.get("project_alias", "") or project_root.resolve().name

        written: list[WrittenTestMeta] = []
        for item in raw.get("written", []):
            try:
                written.append(WrittenTestMeta(
                    name=str(item.get("test_function_name", "")),
                    confidence=int(item.get("confidence_score", 0)),
                    tier=str(item.get("tier", "LOW")),
                    file=str(item.get("test_file_path", "")),
                    edge_case_type=str(item.get("constraint_kind", "")),
                    spec_source=str(item.get("spec_source", "")),
                ))
            except Exception:  # noqa: BLE001
                continue

        scaffolded: list[ScaffoldedMeta] = []
        for item in raw.get("scaffolded", []):
            try:
                scaffolded.append(ScaffoldedMeta(
                    stub_file=str(item.get("stub_file", "")),
                    reason=str(item.get("reason", "")),
                    age_days=int(item.get("age_days", 0)),
                ))
            except Exception:  # noqa: BLE001
                continue

        flagged: list[FlaggedMeta] = []
        for item in raw.get("flagged", []):
            try:
                flagged.append(FlaggedMeta(
                    location=str(item.get("location", "")),
                    reason=str(item.get("reason", "")),
                    edge_case_type=str(item.get("constraint_kind", "")),
                ))
            except Exception:  # noqa: BLE001
                continue

        total = summary.get("gaps_found", len(written) + len(scaffolded) + len(flagged))

        return SyncPayload(
            project_id=pid,
            project_alias=alias,
            run_at=datetime.datetime.now(datetime.UTC),
            quell_version=__version__,
            prs=prs,
            prs_delta=prs_delta,
            edge_cases=EdgeCaseCounts(
                total=int(total),
                written=len(written),
                scaffolded=len(scaffolded),
                flagged=len(flagged),
            ),
            written_tests=written,
            scaffolded_items=scaffolded,
            flagged_items=flagged,
        )
    except Exception:  # noqa: BLE001
        return None


def record_push(payload: SyncPayload) -> None:
    """Append a push record to .quell/sync_history.json for prs_delta tracking."""
    try:
        _SYNC_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        history: list[dict] = []
        if _SYNC_HISTORY.exists():
            try:
                history = json.loads(_SYNC_HISTORY.read_text())
            except Exception:  # noqa: BLE001
                history = []
        history.append({
            "project_id": payload.project_id,
            "prs": payload.prs,
            "run_at": payload.run_at.isoformat(),
        })
        # Keep only the last 100 entries
        history = history[-100:]
        _SYNC_HISTORY.write_text(json.dumps(history, indent=2))
    except Exception:  # noqa: BLE001
        pass
