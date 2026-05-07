"""
Formats CI run results for different output targets.

Supported formats:
  console   — Rich-formatted human-readable output (default)
  json      — Machine-readable JSON for dashboards and external tooling
  github    — GitHub Actions annotations (::notice/::warning/::error)
"""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from quell.score.calculator import ProjectScore
from quell.ci.threshold import ThresholdResult


@dataclass
class CIReport:
    """Full CI run summary."""

    score_before: float
    score_after: float
    fixed_count: int
    skipped_count: int
    total_survivors: int
    threshold_result: ThresholdResult
    dry_run: bool = False
    files_changed: list[str] = field(default_factory=list)


def report_console(report: CIReport, project_score: ProjectScore) -> None:
    """Print a Rich-formatted CI summary to stdout."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    delta = report.score_after - report.score_before
    delta_str = f"+{delta:.0%}" if delta >= 0 else f"{delta:.0%}"
    delta_color = "green" if delta >= 0 else "red"

    status_icon = "✓" if report.threshold_result.passed else "✗"
    status_color = "green" if report.threshold_result.passed else "red"

    summary = (
        f"[{status_color}]{status_icon} {report.threshold_result.message}[/{status_color}]\n\n"
        f"Score: [bold]{report.score_after:.0%}[/bold]  "
        f"Delta: [{delta_color}]{delta_str}[/{delta_color}]  "
        f"Fixed: [green]{report.fixed_count}[/green]  "
        f"Skipped: [yellow]{report.skipped_count}[/yellow]"
    )

    if report.dry_run:
        summary = "[yellow](dry-run)[/yellow] " + summary

    console.print(Panel(summary, title="Quell CI", border_style=status_color))

    if project_score.files:
        table = Table(title="File Scores", show_header=True)
        table.add_column("File", style="blue")
        table.add_column("Score", justify="right")
        table.add_column("Grade", justify="center")
        table.add_column("Killed / Total", justify="right", style="dim")

        for fs in sorted(project_score.files, key=lambda f: f.quell_score):
            grade_color = {"A": "green", "B": "yellow", "C": "yellow", "F": "red"}.get(
                fs.grade, "white"
            )
            table.add_row(
                str(fs.file_path),
                f"{fs.percentage}%",
                f"[{grade_color}]{fs.grade}[/{grade_color}]",
                f"{fs.killed_mutants}/{fs.total_mutants}",
            )

        console.print(table)


def report_json(report: CIReport, output_path: Path | None = None) -> str:
    """
    Serialize CI report to JSON.

    If output_path is given, writes to file. Always returns the JSON string.
    """
    payload = {
        "score_before": report.score_before,
        "score_after": report.score_after,
        "score_delta": report.score_after - report.score_before,
        "fixed": report.fixed_count,
        "skipped": report.skipped_count,
        "total_survivors": report.total_survivors,
        "threshold": report.threshold_result.threshold,
        "threshold_passed": report.threshold_result.passed,
        "dry_run": report.dry_run,
    }
    out = json.dumps(payload, indent=2)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(out, encoding="utf-8")

    return out


def report_github_actions(report: CIReport) -> None:
    """
    Emit GitHub Actions workflow commands.

    Sets output variables and emits annotations so the score shows up in
    PR summaries and the step output.
    """
    pct = int(report.score_after * 100)
    delta = report.score_after - report.score_before
    delta_str = f"+{delta:.1%}" if delta >= 0 else f"{delta:.1%}"

    # Set step outputs (readable via ${{ steps.<id>.outputs.score }})
    print(f"::set-output name=score::{pct}")
    print(f"::set-output name=score_delta::{delta_str}")
    print(f"::set-output name=fixed::{report.fixed_count}")
    print(f"::set-output name=threshold_passed::{str(report.threshold_result.passed).lower()}")

    # Emit summary annotation
    level = "notice" if report.threshold_result.passed else "error"
    print(
        f"::{level}::Quell Score: {pct}% ({delta_str}) | "
        f"Fixed: {report.fixed_count} survivors | "
        f"{report.threshold_result.message}"
    )
