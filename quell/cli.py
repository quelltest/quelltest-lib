"""
Quell CLI — built with Typer.

Commands:
  quell check       Scan specs, find gaps, optionally fix
  quell reproduce   Bug description → failing test
  quell prove       Confidence score for a function/file
  quell score       Project-wide Quell Score + --badge
  quell ci          CI mode: check + threshold + exit code
  quell init        Add [tool.quell] to pyproject.toml
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from quell.core.models import QuellConfig, VerificationStatus

app = typer.Typer(
    name="quell",
    help="Your docstrings say what your code should do. Quell proves it.",
    rich_markup_mode="rich",
)
console = Console()


def _load_config(project_root: Path) -> QuellConfig:
    """Load config from pyproject.toml [tool.quell] or return defaults."""
    try:
        import tomllib
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            data = tomllib.loads(pyproject.read_text())
            quell_cfg = data.get("tool", {}).get("quell", {})
            return QuellConfig(**quell_cfg) if quell_cfg else QuellConfig()
    except Exception:
        pass
    return QuellConfig()


@app.command("check")
def cmd_check(
    target: str = typer.Argument(".", help="File or directory to check"),
    fix: bool = typer.Option(False, "--fix", help="Generate and write verified tests"),
    sources: Optional[str] = typer.Option(
        None, "--sources", help="Comma-separated: docstring,type,mutation"
    ),
    project_root: Path = typer.Option(Path("."), "--root", help="Project root"),
) -> None:
    """Scan specs, find requirement gaps, optionally generate verified tests."""
    from quell.sdk import Quell

    src_list = sources.split(",") if sources else ["docstring", "type"]
    q = Quell(project_root=project_root)

    with console.status("[bold blue]Scanning specifications...[/bold blue]"):
        result = q.check(target, sources=src_list, fix=fix)

    table = Table(title=f"Requirements — {target}", show_header=True)
    table.add_column("Function", style="cyan")
    table.add_column("Kind", style="yellow")
    table.add_column("Description")
    table.add_column("Covered", style="green")

    for req in result.requirements:
        covered = "YES" if req.is_covered else "NO"
        style = "green" if req.is_covered else "red"
        table.add_row(
            req.target_function,
            req.constraint_kind.value,
            req.description[:60] + ("..." if len(req.description) > 60 else ""),
            f"[{style}]{covered}[/{style}]",
        )

    console.print(table)
    console.print(f"\n[bold]Score:[/bold] {result.score:.0%} "
                  f"({len(result.covered)}/{len(result.requirements)} covered)")

    if result.uncovered:
        console.print(
            f"\n[yellow]{len(result.uncovered)} gap(s) found.[/yellow]"
            + (" Run with --fix to generate tests." if not fix else "")
        )

    if fix and result.report_path:
        console.print(
            f"\n[bold]Diagnostic report:[/bold] {result.report_path}\n"
            "[dim]Share this file with the Quell maintainer to improve "
            "rule engine coverage. No source code is included.[/dim]"
        )


@app.command("reproduce")
def cmd_reproduce(
    description: str = typer.Argument(..., help="Bug description in plain English"),
    file: Optional[str] = typer.Option(None, "--file", help="Target source file"),
    project_root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Convert a bug description into a verified failing test."""
    from quell.sdk import Quell

    q = Quell(project_root=project_root)

    with console.status("[bold blue]Analyzing bug description...[/bold blue]"):
        written = q.reproduce(description, file=file)

    if written:
        console.print(Panel(
            "[green]Bug reproduction test written.[/green]\n"
            "The test currently FAILS (bug exists). Fix the code, then run it to confirm.",
            title="quell reproduce",
        ))
    else:
        console.print("[red]Could not generate a verified bug reproduction test.[/red]")
        raise typer.Exit(1)


@app.command("prove")
def cmd_prove(
    file: str = typer.Argument(..., help="Source file to prove"),
    function: Optional[str] = typer.Option(None, "--function", help="Specific function"),
    project_root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Show requirement coverage score for a file or function."""
    from quell.sdk import Quell

    q = Quell(project_root=project_root)

    with console.status("[bold blue]Checking coverage...[/bold blue]"):
        score = q.prove(file, function=function)

    color = "green" if score >= 0.80 else "yellow" if score >= 0.60 else "red"
    label = f"{function or file}"
    console.print(
        Panel(
            f"[{color}]{score:.0%}[/{color}] of requirements proven for [cyan]{label}[/cyan]",
            title="Quell Score",
        )
    )


@app.command("score")
def cmd_score(
    badge: bool = typer.Option(False, "--badge", help="Write badge.svg to .quell/"),
    project_root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Show project-wide Quell Score."""
    from quell.sdk import Quell
    from quell.score.badge import write_badge

    q = Quell(project_root=project_root)

    with console.status("[bold blue]Calculating score...[/bold blue]"):
        project_score = q.score()

    if not project_score.files:
        console.print("[yellow]No requirements found. Add docstrings or Pydantic models.[/yellow]")
        return

    table = Table(title="Quell Score by File")
    table.add_column("File", style="cyan")
    table.add_column("Requirements")
    table.add_column("Covered")
    table.add_column("Score")
    table.add_column("Grade")

    for fs in project_score.files:
        color = "green" if fs.quell_score >= 0.80 else "yellow" if fs.quell_score >= 0.60 else "red"
        table.add_row(
            str(fs.file_path.name),
            str(fs.total_requirements),
            str(fs.covered_requirements),
            f"[{color}]{fs.percentage}%[/{color}]",
            f"[{color}]{fs.grade}[/{color}]",
        )

    console.print(table)
    console.print(f"\n[bold]Project Score:[/bold] {project_score.percentage}%")

    if badge:
        path = write_badge(project_score.total_score, project_root / ".quell")
        console.print(f"[green]Badge written to {path}[/green]")


@app.command("ci")
def cmd_ci(
    target: str = typer.Argument(".", help="File or directory to check"),
    threshold: float = typer.Option(0.0, "--threshold", help="Minimum score (0.0–1.0)"),
    project_root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """CI mode: check requirements and exit 1 if below threshold."""
    from quell.sdk import Quell

    q = Quell(project_root=project_root)
    result = q.check(target)

    console.print(f"Quell Score: {result.score:.0%} | Threshold: {threshold:.0%}")

    if result.score < threshold:
        console.print(
            f"[red]FAIL: {result.score:.0%} < {threshold:.0%} threshold[/red]"
        )
        raise typer.Exit(1)

    console.print("[green]PASS[/green]")


@app.command("init")
def cmd_init(
    project_root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Add [tool.quell] configuration block to pyproject.toml."""
    pyproject = project_root / "pyproject.toml"

    if not pyproject.exists():
        console.print("[red]No pyproject.toml found. Create one first.[/red]")
        raise typer.Exit(1)

    content = pyproject.read_text()
    if "[tool.quell]" in content:
        console.print("[yellow][tool.quell] already exists in pyproject.toml[/yellow]")
        return

    quell_block = """
[tool.quell]
llm_provider = "anthropic"
llm_model = "claude-sonnet-4-5"
max_verification_attempts = 3
verification_timeout_seconds = 30
auto_write = false
enable_docstring = true
enable_types = true
enable_mutations = false
score_threshold = 0.0
"""
    pyproject.write_text(content + quell_block)
    console.print("[green]Added [tool.quell] to pyproject.toml[/green]")
