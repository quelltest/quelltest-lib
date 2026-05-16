"""Rich console singleton and three-bucket output renderer for Quell UI."""
from __future__ import annotations

from rich.console import Console
from rich.rule import Rule

console = Console()

_TIER_COLOR = {"green": "green", "yellow": "yellow", "red": "red"}
_TIER_EMOJI = {"green": "●", "yellow": "●", "red": "●"}


def render_bucketed_summary(
    written: list[dict],  # type: ignore[type-arg]
    scaffolded: list[dict],  # type: ignore[type-arg]
    flagged: list[dict],  # type: ignore[type-arg]
    prs_score: int,
    prs_tier: str,
    prs_tier_label: str,
    avg_confidence: float,
    total: int,
    report_path: str = ".quell/report.json",
) -> None:
    """Render three-bucket output (spec7 §2.3) to the console."""
    coverage_pct = int((len(written) + len(scaffolded)) / total * 100) if total else 0

    console.print()
    console.print(
        f"[bold]Quell scan complete[/bold] — "
        f"[yellow]{total}[/yellow] untested edge cases found"
    )
    console.print()

    # ── WRITTEN ───────────────────────────────────────────────────────────────
    console.print(
        f"[bold green]✓ WRITTEN[/bold green]  ({len(written)})   "
        "Tests generated, passed 5/5 gates, ready to ship."
    )
    for item in written:
        conf = item.get("confidence") or 0
        tier = item.get("tier") or ""
        tier_tag = f"[bold cyan][{tier}][/bold cyan]" if tier else ""
        file_str = item.get("file") or item.get("requirement_id") or ""
        console.print(
            f"                 [dim]→[/dim] [blue]{file_str}[/blue]"
            f"  confidence: {conf}%  {tier_tag}"
        )

    console.print()

    # ── SCAFFOLDED ────────────────────────────────────────────────────────────
    console.print(
        f"[bold yellow]⚠ SCAFFOLDED[/bold yellow] ({len(scaffolded)}) "
        "Test structure written. You finish the assertion."
    )
    for item in scaffolded:
        sf = item.get("scaffold_file") or item.get("source_file") or ""
        console.print(f"                 [dim]→[/dim] [yellow]{sf}[/yellow]")

    console.print()

    # ── FLAGGED ───────────────────────────────────────────────────────────────
    console.print(
        f"[bold red]🚩 FLAGGED[/bold red]   ({len(flagged)})  "
        "Can't auto-test. Here's why and where to look."
    )
    for item in flagged:
        src = item.get("source_file") or ""
        line = item.get("source_line")
        loc = f"{src}:{line}" if line else src
        reason = item.get("reason") or "unknown"
        console.print(
            f"                 [dim]→[/dim] [red]{loc}[/red]"
            f"  [dim]reason: {reason}[/dim]"
        )

    console.print()
    console.print(Rule())

    # ── PRS summary ───────────────────────────────────────────────────────────
    color = _TIER_COLOR.get(prs_tier, "white")
    console.print(
        f"[bold]Production Readiness Score:[/bold] "
        f"[bold {color}]{prs_score}/100[/bold {color}]  "
        f"[dim]({prs_tier_label})[/dim]"
    )
    console.print(
        f"[bold]Edge Case Coverage:[/bold]        "
        f"{coverage_pct}%  [dim]({len(written) + len(scaffolded)} of {total} cases handled)[/dim]"
    )
    if written:
        console.print(
            f"[bold]Avg Test Confidence:[/bold]       "
            f"{avg_confidence:.0f}%  [dim](across {len(written)} WRITTEN tests)[/dim]"
        )
    console.print()
    console.print(f"[dim]Report: {report_path}[/dim]")
    console.print()
