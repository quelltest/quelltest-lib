"""
Quell CLI — built with Typer.

Commands:
  quell scan                    List all surviving mutants
  quell fix                     Interactive fix loop (review one by one)
  quell auto                    Auto-fix all survivors (no prompts)
  quell ci                      CI/CD mode: run mutation testing + auto-fix
  quell score                   Show per-file mutation scores and badge
  quell repair                  Find and strengthen weak AI-generated tests
  quell report                  Show audit log
  quell init                    Add [tool.quell] to pyproject.toml
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from quell.core.models import QuellConfig, VerificationStatus
from quell.core.analyzer import MutationAnalyzer
from quell.core.generator import TestGenerator
from quell.core.verifier import MutantVerifier
from quell.core.writer import TestWriter
from quell.adapters.mutmut_adapter import MutmutAdapter
from quell.adapters.stryker_adapter import StrykerAdapter
from quell.llm.client import LLMClient

app = typer.Typer(
    name="quell",
    help="Quell your mutation testing survivors. Auto-generates verified killing tests.",
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
            quell_config = data.get("tool", {}).get("quell", {})
            if quell_config:
                return QuellConfig(**quell_config)
    except Exception:
        pass
    return QuellConfig()


def _get_adapter(tool: str, project_root: Path):
    """Return the appropriate adapter based on tool flag."""
    if tool == "mutmut":
        return MutmutAdapter(project_root)
    elif tool == "stryker":
        report_candidates = [
            project_root / "reports" / "mutation" / "mutation.json",
            project_root / "mutation-report.json",
        ]
        for candidate in report_candidates:
            if candidate.exists():
                return StrykerAdapter(candidate)
        raise typer.BadParameter("No Stryker report found. Run: npx stryker run --reporters=json")
    else:
        raise typer.BadParameter(f"Unknown tool: {tool}. Use 'mutmut' or 'stryker'.")


@app.command("scan")
def scan(
    tool: str = typer.Option("mutmut", "--tool", "-t", help="mutmut or stryker"),
    project_root: Path = typer.Option(Path("."), "--root", "-r", help="Project root directory"),
):
    """[bold]Scan[/bold] and list all surviving mutants."""

    console.print(Panel.fit("[bold blue]Quell — Scanning for survivors[/bold blue]"))

    config = _load_config(project_root)
    adapter = _get_adapter(tool, project_root)
    analyzer = MutationAnalyzer()

    with console.status("Reading mutation results..."):
        survivors = adapter.read_survivors()
        survivors = [analyzer.analyze(m) for m in survivors]

    if not survivors:
        console.print("[green]✓ No surviving mutants found![/green]")
        return

    table = Table(title=f"Surviving Mutants ({len(survivors)} total)")
    table.add_column("ID", style="cyan", width=6)
    table.add_column("File", style="blue")
    table.add_column("Line", style="yellow", width=6)
    table.add_column("Operator", style="magenta")
    table.add_column("Original → Mutated", style="white")

    for m in survivors:
        table.add_row(
            str(m.id),
            str(m.file_path.name),
            str(m.line_start),
            m.operator.value,
            f"[red]{m.original_code.strip()[:30]}[/red] → [green]{m.mutated_code.strip()[:30]}[/green]",
        )

    console.print(table)
    console.print(f"\n[yellow]Run [bold]quell fix[/bold] to generate and verify killing tests.[/yellow]")


@app.command("fix")
def fix(
    tool: str = typer.Option("mutmut", "--tool", "-t"),
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
    llm_provider: Optional[str] = typer.Option(None, "--llm"),
    mutant_id: Optional[str] = typer.Option(None, "--id", help="Fix only a specific mutant ID"),
):
    """[bold]Interactively[/bold] generate and apply verified killing tests."""
    asyncio.run(_fix_async(tool, project_root, llm_provider, mutant_id))


async def _fix_async(tool: str, project_root: Path, llm_provider: Optional[str], mutant_id: Optional[str]) -> None:
    config = _load_config(project_root)
    if llm_provider:
        config = config.model_copy(update={"llm_provider": llm_provider})

    adapter = _get_adapter(tool, project_root)
    analyzer = MutationAnalyzer()
    llm = LLMClient.from_config(config)
    generator = TestGenerator(llm, config)
    verifier = MutantVerifier(config)
    writer = TestWriter(config)

    with console.status("Reading mutation results..."):
        survivors = adapter.read_survivors()
        survivors = [analyzer.analyze(m) for m in survivors]
        if mutant_id:
            survivors = [m for m in survivors if m.id == mutant_id]

    if not survivors:
        console.print("[green]No survivors to fix![/green]")
        return

    console.print(f"[bold]Found {len(survivors)} surviving mutants.[/bold]\n")

    killed_count = 0
    skipped_count = 0

    for i, mutant in enumerate(survivors, 1):
        console.print(Panel(
            f"[bold cyan]Mutant {mutant.id}[/bold cyan] ({i}/{len(survivors)})\n"
            f"[blue]{mutant.file_path.name}[/blue] line [yellow]{mutant.line_start}[/yellow]\n\n"
            f"[red]- {mutant.original_code.strip()}[/red]\n"
            f"[green]+ {mutant.mutated_code.strip()}[/green]\n\n"
            f"Operator: [magenta]{mutant.operator.value}[/magenta]"
        ))

        # Generate candidate test
        with console.status("Generating killing test..."):
            generated = await generator.generate(mutant)

        console.print("\n[bold]Generated test:[/bold]")
        console.print(Syntax(generated.test_code, "python", theme="monokai"))
        console.print(f"[dim]Generated by: {generated.generated_by}[/dim]")
        console.print(f"[dim]Explanation: {generated.explanation}[/dim]\n")

        # Verify it
        result = None
        with console.status("Verifying test kills the mutant..."):
            for attempt in range(1, config.max_verification_attempts + 1):
                result = verifier.verify(mutant, generated)
                if result.status == VerificationStatus.VERIFIED:
                    break
                if attempt < config.max_verification_attempts:
                    console.print(f"[yellow]Attempt {attempt} failed ({result.status.value}), retrying...[/yellow]")
                    generated = await generator.generate(mutant)

        if result and result.status == VerificationStatus.VERIFIED:
            console.print("[bold green]✓ Verified! Test kills the mutant.[/bold green]")

            # Ask user
            confirm = typer.confirm("Write this test to the test file?", default=True)
            if confirm:
                success = writer.write(generated, mutant.id)
                if success:
                    console.print(f"[green]✓ Written to {generated.test_file_path}[/green]\n")
                    killed_count += 1
                else:
                    console.print("[red]✗ Write failed. Backup restored.[/red]\n")
            else:
                skipped_count += 1
        else:
            status_val = result.status.value if result else "unknown"
            console.print(f"[red]✗ Could not generate a verified killing test ({status_val})[/red]")
            if result and result.status == VerificationStatus.DOESNT_KILL_MUTANT:
                console.print("[dim]This may be an equivalent mutant (semantically identical to original).[/dim]")
            skipped_count += 1

        console.print("─" * 60)

    # Summary
    console.print(Panel.fit(
        f"[bold]Done![/bold]\n"
        f"[green]✓ Killed: {killed_count}[/green]  "
        f"[yellow]Skipped: {skipped_count}[/yellow]  "
        f"[dim]Total: {len(survivors)}[/dim]"
    ))


@app.command("auto")
def auto(
    tool: str = typer.Option("mutmut", "--tool", "-t"),
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
    llm_provider: Optional[str] = typer.Option(None, "--llm"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be written without writing"),
):
    """[bold]Auto-fix[/bold] all survivors without interactive prompts."""
    asyncio.run(_auto_async(tool, project_root, llm_provider, dry_run))


async def _auto_async(tool: str, project_root: Path, llm_provider: Optional[str], dry_run: bool) -> None:
    config = _load_config(project_root)
    config = config.model_copy(update={"auto_write": True})
    if llm_provider:
        config = config.model_copy(update={"llm_provider": llm_provider})

    adapter = _get_adapter(tool, project_root)
    analyzer = MutationAnalyzer()
    llm = LLMClient.from_config(config)
    generator = TestGenerator(llm, config)
    verifier = MutantVerifier(config)
    writer = TestWriter(config)

    survivors = adapter.read_survivors()
    survivors = [analyzer.analyze(m) for m in survivors]

    console.print(f"[bold]Auto-fixing {len(survivors)} survivors...[/bold]\n")

    results: dict[str, int] = {"verified": 0, "failed": 0, "written": 0}

    for mutant in survivors:
        result = None
        with console.status(f"Processing mutant {mutant.id}..."):
            generated = await generator.generate(mutant)

            for attempt in range(config.max_verification_attempts):
                result = verifier.verify(mutant, generated)
                if result.status == VerificationStatus.VERIFIED:
                    break
                if attempt < config.max_verification_attempts - 1:
                    generated = await generator.generate(mutant)

        if result and result.status == VerificationStatus.VERIFIED:
            results["verified"] += 1
            if not dry_run:
                if writer.write(generated, mutant.id):
                    results["written"] += 1
                    console.print(f"[green]✓ {mutant.id}[/green] → {generated.test_function_name}")
            else:
                console.print(f"[blue]DRY-RUN[/blue] {mutant.id} → {generated.test_function_name}")
        else:
            results["failed"] += 1
            status_val = result.status.value if result else "unknown"
            console.print(f"[red]✗ {mutant.id}[/red] → {status_val}")

    console.print(f"\n[bold]Results:[/bold] {results}")


@app.command("report")
def report(
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """Show the [bold]audit log[/bold] of all Quell actions."""
    config = _load_config(project_root)

    if not config.audit_log_path.exists():
        console.print("[yellow]No audit log found yet. Run quell fix first.[/yellow]")
        return

    lines = config.audit_log_path.read_text().strip().splitlines()

    table = Table(title="Quell Audit Log")
    table.add_column("Timestamp", style="dim")
    table.add_column("Mutant ID", style="cyan")
    table.add_column("Action", style="yellow")
    table.add_column("File")
    table.add_column("Test Function")

    for line in lines[-limit:]:
        entry = json.loads(line)
        table.add_row(
            entry.get("timestamp", "")[:19],
            entry.get("mutant_id", ""),
            entry.get("action", ""),
            Path(entry.get("file_path", "")).name if entry.get("file_path") else "",
            entry.get("test_function_name", ""),
        )

    console.print(table)


@app.command("init")
def init(
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
):
    """Add [tool.quell] configuration to pyproject.toml."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        console.print("[red]No pyproject.toml found.[/red]")
        raise typer.Exit(1)

    content = pyproject.read_text()
    if "[tool.quell]" in content:
        console.print("[yellow]quell config already exists in pyproject.toml[/yellow]")
        return

    quell_config = """
[tool.quell]
llm_provider = "anthropic"           # "anthropic" | "openai" | "ollama"
llm_model = "claude-sonnet-4-5"
max_verification_attempts = 3
verification_timeout_seconds = 30
auto_write = false                   # set true for CI/CD usage
"""
    pyproject.write_text(content + quell_config)
    console.print("[green]✓ Added [tool.quell] to pyproject.toml[/green]")
    console.print("[dim]Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in your environment.[/dim]")


@app.command("ci")
def ci(
    threshold: float = typer.Option(0.0, "--threshold", "-t", help="Fail if mutation score < threshold (0-1)"),
    diff_only: bool = typer.Option(False, "--diff-only", help="Only mutate lines changed vs origin/main"),
    base_ref: str = typer.Option("origin/main", "--base", help="Base git ref for --diff-only"),
    report: str = typer.Option("console", "--report", help="Output format: console | json | github"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change, don't write"),
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
    tool: str = typer.Option("mutmut", "--tool", "-t", help="mutmut or stryker"),
):
    """
    [bold]CI/CD mode[/bold] — run mutation testing + auto-fix survivors.

    Fails with exit code 1 if the mutation score is below --threshold.
    Use [bold]--diff-only[/bold] in PR pipelines to only mutate changed lines (2-3 min vs 15-30 min).

    Examples:
      quell ci                          # full project, no threshold
      quell ci --threshold 0.80         # fail if score < 80%
      quell ci --diff-only              # PR mode: only changed lines
      quell ci --report json            # output JSON for dashboards
    """
    asyncio.run(_ci_async(threshold, diff_only, base_ref, report, dry_run, project_root, tool))


async def _ci_async(
    threshold: float,
    diff_only: bool,
    base_ref: str,
    report_format: str,
    dry_run: bool,
    project_root: Path,
    tool: str,
) -> None:
    from quell.ci.runner import run_mutmut_full, run_mutmut_targeted
    from quell.ci.diff_parser import get_changed_lines
    from quell.ci.threshold import check_threshold
    from quell.ci.reporter import CIReport, report_console, report_json, report_github_actions
    from quell.score.calculator import calculate_score
    from quell.score.tracker import record_score

    config = _load_config(project_root)
    config = config.model_copy(update={"auto_write": not dry_run})

    console.print(Panel.fit("[bold blue]Quell CI[/bold blue]"))

    # Record score before
    score_before = 0.0
    try:
        before_score = calculate_score(project_root)
        score_before = before_score.total_score
        console.print(f"Score before: [bold]{before_score.percentage}%[/bold]")
    except FileNotFoundError:
        console.print("[dim]No prior mutation results found — running mutation testing...[/dim]")

    # Run mutation testing
    if diff_only:
        changed = get_changed_lines(base_ref=base_ref, project_root=project_root)
        if not changed:
            console.print("[yellow]No Python file changes detected vs base. Nothing to mutate.[/yellow]")
            raise typer.Exit(0)
        console.print(f"[dim]Targeting {len(changed)} changed file(s) (--diff-only)[/dim]")
        run_mutmut_targeted(changed, project_root)
    else:
        run_mutmut_full(project_root)

    # Fix survivors
    adapter = _get_adapter(tool, project_root)
    analyzer = MutationAnalyzer()
    llm = LLMClient.from_config(config)
    generator = TestGenerator(llm, config)
    verifier = MutantVerifier(config)
    writer = TestWriter(config)

    with console.status("Analyzing survivors..."):
        survivors = adapter.read_survivors()
        survivors = [analyzer.analyze(m) for m in survivors]

    if not survivors:
        console.print("[green]✓ No surviving mutants.[/green]")
    else:
        console.print(f"[bold]{len(survivors)} surviving mutants — generating killing tests...[/bold]")

    fixed = 0
    skipped = 0

    for mutant in survivors:
        generated = await generator.generate(mutant)
        verified = False

        for _ in range(config.max_verification_attempts):
            vr = verifier.verify(mutant, generated)
            if vr.status == VerificationStatus.VERIFIED:
                verified = True
                break
            generated = await generator.generate(mutant)

        if verified:
            if not dry_run and writer.write(generated, mutant.id):
                fixed += 1
                console.print(f"  [green]✓[/green] {mutant.id} → {generated.test_function_name}")
            else:
                skipped += 1
                console.print(f"  [blue]~[/blue] {mutant.id} (dry-run)")
        else:
            skipped += 1
            console.print(f"  [yellow]?[/yellow] {mutant.id} — could not verify")

    # Calculate final score and check threshold
    try:
        after_score = calculate_score(project_root)
        record_score(after_score)
    except FileNotFoundError:
        from quell.score.calculator import ProjectScore
        after_score = ProjectScore()

    score_after = after_score.total_score
    threshold_result = check_threshold(after_score, threshold)

    ci_report = CIReport(
        score_before=score_before,
        score_after=score_after,
        fixed_count=fixed,
        skipped_count=skipped,
        total_survivors=len(survivors),
        threshold_result=threshold_result,
        dry_run=dry_run,
    )

    if report_format == "json":
        out = report_json(ci_report, output_path=project_root / ".quell" / "ci-report.json")
        console.print(out)
    elif report_format == "github":
        report_github_actions(ci_report)
    else:
        report_console(ci_report, after_score)

    if not threshold_result.passed:
        raise typer.Exit(1)


@app.command("score")
def score(
    badge: bool = typer.Option(False, "--badge", help="Generate .quell/badge.svg"),
    format: str = typer.Option("console", "--format", help="Output format: console | json"),
    compare: Optional[str] = typer.Option(None, "--compare", help="Compare score against a label in history"),
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
):
    """
    Show per-file [bold]mutation scores[/bold] and generate a README badge.

    Examples:
      quell score                   # per-file table
      quell score --badge           # generate .quell/badge.svg
      quell score --format json     # JSON output
    """
    from quell.score.calculator import calculate_score
    from quell.score.badge import write_badge
    from quell.score.tracker import get_score_delta, get_score_history

    try:
        project_score = calculate_score(project_root)
    except FileNotFoundError as e:
        console.print(Panel(
            f"[red]Error:[/red] {e}\n\n"
            "Run mutation testing first:\n"
            "  [bold]mutmut run[/bold]\n\n"
            "Then run: [bold]quell score[/bold]",
            title="Quell",
            border_style="red",
        ))
        raise typer.Exit(1)

    if format == "json":
        import json
        data = {
            "total_score": project_score.total_score,
            "percentage": project_score.percentage,
            "total_mutants": project_score.total_mutants,
            "killed_mutants": project_score.killed_mutants,
            "survived_mutants": project_score.survived_mutants,
            "files": [
                {
                    "path": str(f.file_path),
                    "score": f.quell_score,
                    "percentage": f.percentage,
                    "grade": f.grade,
                    "total": f.total_mutants,
                    "killed": f.killed_mutants,
                    "survived": f.survived_mutants,
                }
                for f in project_score.files
            ],
        }
        console.print(json.dumps(data, indent=2))
    else:
        from rich.table import Table

        # Overall score header
        pct = project_score.percentage
        score_color = "green" if pct >= 80 else "yellow" if pct >= 60 else "red"
        console.print(Panel.fit(
            f"[bold]Quell Score: [{score_color}]{pct}%[/{score_color}][/bold]  "
            f"[dim]{project_score.killed_mutants}/{project_score.total_mutants} mutants killed[/dim]",
            title="Quell Score",
        ))

        if project_score.files:
            table = Table(show_header=True, header_style="bold")
            table.add_column("File", style="blue")
            table.add_column("Score", justify="right")
            table.add_column("Grade", justify="center")
            table.add_column("Killed / Total", justify="right", style="dim")
            table.add_column("Survived", justify="right", style="red")

            for fs in project_score.files:
                grade_color = {"A": "green", "B": "yellow", "C": "yellow", "F": "red"}.get(fs.grade, "white")
                pct_color = "green" if fs.percentage >= 80 else "yellow" if fs.percentage >= 60 else "red"
                table.add_row(
                    str(fs.file_path),
                    f"[{pct_color}]{fs.percentage}%[/{pct_color}]",
                    f"[{grade_color}]{fs.grade}[/{grade_color}]",
                    f"{fs.killed_mutants}/{fs.total_mutants}",
                    str(fs.survived_mutants),
                )

            console.print(table)

        # Show delta from last run if history exists
        delta = get_score_delta(project_score, project_root / ".quell" / "history.json")
        if delta is not None:
            delta_str = f"+{delta:.1%}" if delta >= 0 else f"{delta:.1%}"
            delta_color = "green" if delta >= 0 else "red"
            console.print(f"[dim]Delta from last run: [{delta_color}]{delta_str}[/{delta_color}][/dim]")

    if badge:
        from quell.score.badge import write_badge as _write_badge
        badge_path = _write_badge(project_score.total_score, project_root / ".quell")
        console.print(f"\n[green]✓ Badge written to {badge_path}[/green]")
        console.print(f'[dim]Add to README: ![Quell Score]({badge_path})[/dim]')


@app.command("repair")
def repair(
    test_dir: Path = typer.Argument(Path("tests/"), help="Test directory to repair"),
    source_dir: Path = typer.Option(Path("src/"), "--source", help="Source directory to mutate"),
    show_only: bool = typer.Option(False, "--show-only", help="Show what's weak without fixing"),
    llm_provider: Optional[str] = typer.Option(None, "--llm"),
    project_root: Path = typer.Option(Path("."), "--root", "-r"),
):
    """
    [bold]Repair[/bold] AI-generated test suites.

    Finds tests that pass but don't actually verify behavior, then
    strengthens them automatically. Use this after generating tests with
    Copilot, Cursor, or Qodo to prove they catch real bugs.

    Examples:
      quell repair tests/                # repair all tests
      quell repair tests/ --show-only   # show gaps without fixing
      quell repair tests/ --source src/ # specify source dir
    """
    from quell.repair.engine import RepairEngine

    config = _load_config(project_root)
    if llm_provider:
        config = config.model_copy(update={"llm_provider": llm_provider})

    console.print(Panel.fit("[bold blue]Quell Repair[/bold blue]"))
    console.print(f"Test directory: [blue]{test_dir}[/blue]")
    console.print(f"Source directory: [blue]{source_dir}[/blue]")

    if show_only:
        console.print("[yellow](show-only mode — no files will be modified)[/yellow]\n")

    engine = RepairEngine(config, project_root)

    with console.status("Running repair pipeline..."):
        result = engine.repair(
            test_dir=test_dir,
            source_dir=source_dir,
            show_only=show_only,
        )

    delta_str = f"+{result.score_delta:.1%}" if result.score_delta >= 0 else f"{result.score_delta:.1%}"
    delta_color = "green" if result.score_delta >= 0 else "red"

    console.print(Panel.fit(
        f"[bold]Repair complete![/bold]\n\n"
        f"[green]Fixed: {result.fixed}[/green]  "
        f"[yellow]Skipped: {result.skipped}[/yellow]  "
        f"[red]Failed: {result.failed}[/red]\n\n"
        f"Score: {result.score_before:.0%} → {result.score_after:.0%}  "
        f"([{delta_color}]{delta_str}[/{delta_color}])",
        title="Quell Repair",
    ))


if __name__ == "__main__":
    app()
