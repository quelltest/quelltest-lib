# CLAUDE.md — Quell

> **Read this entire file before touching any code.**
> This is the authoritative guide for AI assistants working on the Quell codebase.

---

## What Quell Is (The One-Sentence Truth)

**Quell is the verification layer for AI-generated tests — it proves every test actually catches real bugs, not just achieves coverage.**

Every other tool (Qodo, Copilot, Cursor) generates tests that look green on a dashboard but are weak — they cover lines without verifying behavior. Quell uses mutation testing as a proof engine: if a test doesn't kill a mutant, it doesn't count. Only verified tests ship.

---

## Why This Matters Right Now

Production incidents from AI-generated code increased 43% YoY in 2025. Teams using Copilot and Cursor are shipping more code faster, but their test suites are full of tests that pass without actually catching bugs. Quell fixes this. It's not a mutation testing tool — mutation testing is how Quell *proves* correctness. The product is verified test synthesis.

---

## Positioning (Use This Exact Language)

```
Every other tool:   LLM → test → ✓ green (coverage achieved, but weak)
Quell:              LLM → test → prove it kills a mutant → ✓ actually strong
```

**Tagline:** "Quell verifies your AI-generated tests actually catch bugs."
**Not:** "Quell fixes your mutation testing survivors." (too niche)

---

## CRITICAL: Library Changes Required

The existing codebase (from QUELL_SPEC.md) has several things that MUST be changed before building. Read every item here.

---

### CHANGE 1: mutmut Adapter Must Target v3.x (BREAKING)

The original spec's `mutmut_adapter.py` targets mutmut 2.x API. **mutmut is now at v3.5.0 (Feb 2026) with a completely different execution model.**

**What changed in mutmut 3.x:**
- Uses fork-based execution (not subprocess-per-mutant)
- `mutmut results` output format changed — it now outputs a table, not raw text
- `mutmut apply <id>` still works but ID format changed
- `mutmut browse` is the new TUI (ignore this for programmatic use)
- Internal DB is still SQLite at `.mutmut-cache`
- Python ≥3.10 required (was ≥3.6)
- Uses libcst internally for parsing

**New `mutmut_adapter.py` approach — query the SQLite DB directly:**

```python
# mutmut 3.x stores results in .mutmut-cache (SQLite)
# Schema: mutant table with columns: id, source_path, mutation, status, tests
import sqlite3
from pathlib import Path

DB_PATH = Path(".mutmut-cache")

def read_mutmut3_survivors(project_root: Path) -> list[SurvivedMutant]:
    db = project_root / ".mutmut-cache"
    if not db.exists():
        raise FileNotFoundError(
            "No .mutmut-cache found. Run: mutmut run"
        )
    
    conn = sqlite3.connect(db)
    # mutmut 3.x table: MutantStatus, columns vary by version
    # Use: SELECT * FROM MutantStatus WHERE status = 'survived'
    cursor = conn.execute(
        "SELECT id, source_path, mutation, status FROM MutantStatus WHERE status = 'survived'"
    )
    rows = cursor.fetchall()
    conn.close()
    # parse rows into SurvivedMutant objects
```

**IMPORTANT:** Before implementing the adapter, run `mutmut run` on a sample project, then inspect the actual `.mutmut-cache` SQLite schema with:
```bash
sqlite3 .mutmut-cache ".schema"
sqlite3 .mutmut-cache "SELECT * FROM sqlite_master WHERE type='table'"
```
Use the actual schema found. Do NOT assume table/column names from old docs.

**Also note:** mutmut 3.x does NOT work on Windows without WSL. Document this.

**Competitor to differentiate from:** `mutmut-mcp` (wdm0006/mutmut-mcp) already exists as an MCP server for mutmut. It only RUNS mutation tests and reports results. It does NOT generate killing tests, does NOT verify them, does NOT write to test files. Quell is downstream of mutmut-mcp, not competing with it.

---

### CHANGE 2: Add `quell ci` Command (Highest Priority Addition)

This is the most impactful missing feature. Add to `cli.py`:

```bash
quell ci                          # run mutation testing + generate verified fixes
quell ci --threshold 80           # fail (exit 1) if mutation score < 80%
quell ci --diff-only              # only mutate lines changed vs git main/HEAD
quell ci --report json            # output JSON for CI dashboards
quell ci --dry-run                # show what would change, don't write
```

**The `--diff-only` flag is the killer feature.** Full mutation testing takes 15-30 minutes on large projects. `--diff-only` gets it to 2-3 minutes by only mutating lines in the git diff. This makes Quell viable in every PR pipeline.

Implementation:
1. Get changed lines: `git diff --unified=0 origin/main...HEAD` → parse to get file + line ranges
2. Pass line ranges to mutmut: `mutmut run --paths-to-mutate <file> --lines <start>-<end>`
3. Run Quell's fix loop on survivors
4. Exit code: 0 = all survivors fixed OR mutation score above threshold; 1 = failures

```python
@app.command("ci")
def ci(
    threshold: float = typer.Option(0.0, "--threshold", "-t"),
    diff_only: bool = typer.Option(False, "--diff-only"),
    report: str = typer.Option("console", "--report"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    project_root: Path = typer.Option(Path("."), "--root"),
):
    """CI/CD mode: run mutation testing + auto-fix survivors. Fails if threshold not met."""
```

---

### CHANGE 3: Add `quell score` Command + Badge Generation

The mutation score badge is the viral growth mechanism. Add:

```bash
quell score                       # show per-file mutation scores
quell score --badge               # generate SVG badge → .quell/badge.svg
quell score --format json         # JSON output for dashboards
quell score --compare main        # delta from main branch
```

**Badge format** (generate as SVG, same style as shields.io):
```
[quell score | 87%]    → green if >80%, yellow if 60-80%, red if <60%
```

Host badge at `https://quell.dev/badge/{github_user}/{repo}` (cloud feature).
Locally, `quell score --badge` writes `.quell/badge.svg`.

Add to README template: `![Quell Score](.quell/badge.svg)`

---

### CHANGE 4: Add `quell repair` Command

The enterprise use case — repair AI-generated test suites:

```bash
quell repair tests/               # find weak tests, strengthen them
quell repair tests/ --source src/ # full project repair
quell repair tests/ --show-only   # show what's weak without fixing
```

This is different from `quell fix`:
- `quell fix` reads mutmut/Stryker results that user ran manually
- `quell repair` runs mutation testing internally, finds gaps, fixes them — zero manual steps

```python
@app.command("repair")
def repair(
    test_dir: Path = typer.Argument(Path("tests/")),
    source_dir: Path = typer.Option(Path("src/"), "--source"),
    show_only: bool = typer.Option(False, "--show-only"),
):
    """
    Repair AI-generated test suites. Finds tests that pass but don't 
    actually verify behavior, then strengthens them automatically.
    
    Use this if you've generated tests with Copilot/Cursor/Qodo and want
    to verify they actually catch bugs.
    """
```

---

### CHANGE 5: Add `quell-mcp` MCP Server Module

Add `quell/mcp_server.py`. This exposes Quell's engine to AI coding agents (Claude Code, Cursor, Devin).

```python
# quell/mcp_server.py
# Run with: uvx quell-mcp  OR  python -m quell.mcp_server

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("quell")

@server.tool()
async def verify_test(test_code: str, source_file: str) -> dict:
    """
    Verify that a test actually kills mutations in the source file.
    Returns: {verified: bool, kills_mutants: int, score_delta: float}
    """

@server.tool()  
async def get_survivors(source_file: str) -> list[dict]:
    """Get all surviving mutants for a file."""

@server.tool()
async def generate_killing_test(mutant_id: str, source_file: str) -> dict:
    """Generate a verified killing test for a specific mutant."""

@server.tool()
async def get_quell_score(file_path: str | None = None) -> dict:
    """Get current mutation score. If file_path is None, returns project score."""
```

**Dependencies to add for MCP:**
```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]
```

**Entry point to add in pyproject.toml:**
```toml
[project.scripts]
quell = "quell.cli:app"
quell-mcp = "quell.mcp_server:main"
```

**Why this matters:** AI coding agents that generate tests can now call `quell.verify_test()` to prove their tests catch bugs before committing. Quell becomes infrastructure, not just a developer tool.

---

### CHANGE 6: Restructure Package for Expanded Scope

The original flat structure is too small. Use this structure:

```
quell/
├── __init__.py
├── cli.py                        ← all CLI commands
├── core/
│   ├── models.py                 ← Pydantic models (keep, no changes)
│   ├── analyzer.py               ← mutation classifier (keep)
│   ├── generator.py              ← test generator (keep)
│   ├── verifier.py               ← verification engine (keep, it's the moat)
│   └── writer.py                 ← libcst injector (keep)
├── adapters/
│   ├── base.py
│   ├── mutmut_adapter.py         ← UPDATE for mutmut 3.x
│   └── stryker_adapter.py        ← keep, Stryker schema is stable
├── ci/
│   ├── __init__.py
│   ├── runner.py                 ← NEW: runs mutmut/stryker programmatically
│   ├── diff_parser.py            ← NEW: git diff → changed line ranges
│   ├── threshold.py              ← NEW: score checking, exit codes
│   └── reporter.py               ← NEW: JSON/console/GitHub Actions output
├── score/
│   ├── __init__.py
│   ├── calculator.py             ← NEW: mutation score per file/project
│   ├── badge.py                  ← NEW: SVG badge generation
│   └── tracker.py                ← NEW: score history in .quell/history.json
├── repair/
│   ├── __init__.py
│   └── engine.py                 ← NEW: wraps ci/runner + fix loop
├── mcp_server.py                 ← NEW: MCP server
├── sdk.py                        ← NEW: clean programmatic API
├── llm/
│   ├── client.py
│   ├── prompts.py                ← UPDATE: add repair + score prompts
│   └── providers/
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       └── ollama_provider.py
└── ui/
    ├── console.py
    ├── progress.py
    └── diff.py
```

---

### CHANGE 7: Add `quell/sdk.py` — Clean Programmatic API

The SDK is what enterprise users and AI agents use. Keep it simple and clean:

```python
# quell/sdk.py
"""
Quell SDK — programmatic API for verifying AI-generated tests.

Usage:
    from quell import Quell
    
    q = Quell()                              # uses config from pyproject.toml
    q = Quell(llm="ollama", model="codellama")  # local LLM
    
    # Verify a test you generated
    result = q.verify_test(
        test_code="def test_foo(): assert foo(0) == 'zero'",
        source_file="src/utils.py"
    )
    result.verified        # True/False
    result.explanation     # why it passed or failed
    result.score_delta     # mutation score change if applied
    
    # Get current project score
    score = q.get_score()
    score.total            # 0.87 (87%)
    score.by_file          # {"src/utils.py": 0.91, "src/payments.py": 0.72}
    
    # Fix all survivors
    results = q.fix_all(source="mutmut")
    results.fixed          # number fixed
    results.skipped        # number skipped (equivalent mutants)
    results.score_before   # 0.71
    results.score_after    # 0.89
"""

class Quell:
    def __init__(
        self,
        llm: str = "anthropic",
        model: str | None = None,
        project_root: Path = Path("."),
        local: bool = False,       # if True, use Ollama regardless of other settings
    ):
        ...
    
    def verify_test(self, test_code: str, source_file: str | Path) -> VerifyResult:
        """
        Core method. Given test code and source file, verify the test
        kills at least one mutant AND passes on original code.
        """
    
    def get_score(self, path: str | Path | None = None) -> ScoreResult:
        """Get current mutation score. Runs mutmut if needed."""
    
    def fix_all(
        self, 
        source: str = "mutmut",
        auto_write: bool = False,
        threshold: float = 0.0,
    ) -> FixResult:
        """Fix all surviving mutants. Returns summary."""
    
    def repair(self, test_dir: Path, source_dir: Path) -> RepairResult:
        """Find and fix weak tests in test_dir."""
```

---

### CHANGE 8: Update `pyproject.toml` for New Structure

```toml
[project]
name = "quell"
version = "0.2.0"
description = "Verified AI test synthesis — proves every generated test catches real bugs"
# ... (keep author, license, etc.)

dependencies = [
    "typer>=0.12.0",
    "rich>=13.7.0",
    "pydantic>=2.6.0",
    "libcst>=1.8.0",          # UPDATE: was 1.3.0, current is 1.8.6
    "anthropic>=0.40.0",      # UPDATE: was 0.28.0
    "openai>=1.50.0",         # UPDATE: was 1.30.0
    "httpx>=0.27.0",
    "gitpython>=3.1.0",       # NEW: for diff-only CI mode
]

[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]          # NEW
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.8.0",             # UPDATE
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
    "mutmut>=3.5.0",           # NEW: needed for integration tests
]

[project.scripts]
quell = "quell.cli:app"
quell-mcp = "quell.mcp_server:main"    # NEW
```

---

## New Modules: Full Implementation Specs

### `quell/ci/diff_parser.py`

```python
"""
Parses git diff output to get changed line ranges.
Used by `quell ci --diff-only` to only mutate changed code.
"""
import subprocess
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ChangedLines:
    file_path: Path
    line_ranges: list[tuple[int, int]]   # [(start, end), ...]


def get_changed_lines(
    base_ref: str = "origin/main",
    project_root: Path = Path(".")
) -> list[ChangedLines]:
    """
    Run `git diff --unified=0 <base_ref>...HEAD` and parse which lines changed.
    Returns one ChangedLines per modified Python file.
    """
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{base_ref}...HEAD"],
        capture_output=True, text=True, cwd=project_root
    )
    return _parse_unified_diff(result.stdout, project_root)


def _parse_unified_diff(diff_output: str, root: Path) -> list[ChangedLines]:
    """
    Parse unified diff format to extract file → changed line ranges.
    
    Format:
    --- a/src/payments.py
    +++ b/src/payments.py
    @@ -47,3 +47,5 @@    ← new file starts at 47, spans 5 lines
    """
    result = []
    current_file = None
    current_ranges = []
    
    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            if current_file and current_ranges:
                result.append(ChangedLines(
                    file_path=root / current_file,
                    line_ranges=current_ranges,
                ))
            current_file = line[6:]   # strip "+++ b/"
            current_ranges = []
        elif line.startswith("@@"):
            # Parse: @@ -old_start,old_count +new_start,new_count @@
            import re
            match = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or "1")
                if count > 0:
                    current_ranges.append((start, start + count - 1))
    
    if current_file and current_ranges:
        result.append(ChangedLines(
            file_path=root / current_file,
            line_ranges=current_ranges,
        ))
    
    # Filter to Python files only
    return [c for c in result if c.file_path.suffix == ".py"]
```

---

### `quell/ci/runner.py`

```python
"""
Runs mutmut programmatically for CI mode.
Handles both full-project runs and diff-only targeted runs.
"""
import subprocess
from pathlib import Path
from quell.ci.diff_parser import ChangedLines


def run_mutmut_full(project_root: Path) -> int:
    """Run full mutation testing. Returns exit code."""
    result = subprocess.run(
        ["mutmut", "run"],
        cwd=project_root,
        capture_output=False,  # show progress to user
    )
    return result.returncode


def run_mutmut_targeted(changed: list[ChangedLines], project_root: Path) -> int:
    """
    Run mutation testing only on changed lines.
    Uses mutmut's path + function targeting to stay fast.
    
    NOTE: mutmut 3.x supports `mutmut run "module.function*"` pattern.
    We identify which functions contain the changed lines, then target them.
    """
    # Build list of module paths to mutate
    # Format: "src.payments" not "src/payments.py"
    modules_to_mutate = []
    for change in changed:
        module_path = _file_to_module(change.file_path, project_root)
        if module_path:
            modules_to_mutate.append(module_path)
    
    if not modules_to_mutate:
        return 0  # nothing to mutate
    
    patterns = " ".join(f'"{m}*"' for m in modules_to_mutate)
    result = subprocess.run(
        ["mutmut", "run"] + modules_to_mutate,
        cwd=project_root,
        capture_output=False,
    )
    return result.returncode


def _file_to_module(file_path: Path, project_root: Path) -> str | None:
    """Convert src/payments.py → src.payments"""
    try:
        rel = file_path.relative_to(project_root)
        return str(rel.with_suffix("")).replace("/", ".")
    except ValueError:
        return None
```

---

### `quell/score/calculator.py`

```python
"""
Calculates Quell Score — mutation-verified coverage per file/project.

Quell Score = verified_lines / total_lines × 100

This is a stronger metric than coverage% because it requires tests
to actually catch mutations, not just execute lines.
"""
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FileScore:
    file_path: Path
    total_mutants: int
    killed_mutants: int
    survived_mutants: int
    quell_score: float         # 0.0 to 1.0
    
    @property
    def percentage(self) -> int:
        return int(self.quell_score * 100)
    
    @property
    def grade(self) -> str:
        if self.quell_score >= 0.80: return "A"
        if self.quell_score >= 0.60: return "B"
        if self.quell_score >= 0.40: return "C"
        return "F"


@dataclass
class ProjectScore:
    files: list[FileScore] = field(default_factory=list)
    
    @property
    def total_score(self) -> float:
        if not self.files: return 0.0
        total = sum(f.total_mutants for f in self.files)
        if total == 0: return 0.0
        killed = sum(f.killed_mutants for f in self.files)
        return killed / total
    
    @property
    def percentage(self) -> int:
        return int(self.total_score * 100)


def calculate_score(project_root: Path = Path(".")) -> ProjectScore:
    """Read mutmut cache and calculate scores per file."""
    db = project_root / ".mutmut-cache"
    if not db.exists():
        raise FileNotFoundError("Run mutmut first: mutmut run")
    
    conn = sqlite3.connect(db)
    # Inspect actual schema at runtime to handle mutmut version differences
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = [t[0] for t in tables]
    
    # mutmut 3.x uses MutantStatus table
    # Adapt based on what's actually in the DB
    if "MutantStatus" in table_names:
        return _calculate_from_mutmut3(conn)
    else:
        raise ValueError(f"Unknown mutmut cache schema. Tables: {table_names}")


def _calculate_from_mutmut3(conn: sqlite3.Connection) -> ProjectScore:
    """Parse mutmut 3.x schema."""
    # Get actual columns first
    cols = conn.execute("PRAGMA table_info(MutantStatus)").fetchall()
    col_names = [c[1] for c in cols]
    
    # Build query based on available columns
    rows = conn.execute("SELECT * FROM MutantStatus").fetchall()
    
    # Group by file, count killed vs survived
    from collections import defaultdict
    by_file: dict[str, dict] = defaultdict(lambda: {"total": 0, "killed": 0, "survived": 0})
    
    for row in rows:
        row_dict = dict(zip(col_names, row))
        # Common column names in mutmut 3.x: source_path, status
        source = row_dict.get("source_path", row_dict.get("file", "unknown"))
        status = str(row_dict.get("status", "")).lower()
        
        by_file[source]["total"] += 1
        if "killed" in status or "timeout" in status:
            by_file[source]["killed"] += 1
        elif "survived" in status:
            by_file[source]["survived"] += 1
    
    conn.close()
    
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
```

---

### `quell/score/badge.py`

```python
"""
Generates SVG badges for Quell Score.
Mimics shields.io style for README embedding.

Usage:
    badge_svg = generate_badge(score=0.87)
    Path(".quell/badge.svg").write_text(badge_svg)
"""

def generate_badge(score: float) -> str:
    """
    Generate a shields.io-style SVG badge.
    score is 0.0 to 1.0
    """
    pct = int(score * 100)
    
    if score >= 0.80:
        color = "#4c1"        # green
    elif score >= 0.60:
        color = "#dfb317"     # yellow
    else:
        color = "#e05d44"     # red
    
    label = "quell score"
    value = f"{pct}%"
    
    label_width = len(label) * 6 + 10
    value_width = len(value) * 6 + 10
    total_width = label_width + value_width
    
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total_width}" height="20">
    <linearGradient id="s" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <clipPath id="r">
        <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
    </clipPath>
    <g clip-path="url(#r)">
        <rect width="{label_width}" height="20" fill="#555"/>
        <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
        <rect width="{total_width}" height="20" fill="url(#s)"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="110">
        <text x="{label_width * 5}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{label}</text>
        <text x="{label_width * 5}" y="140" transform="scale(.1)">{label}</text>
        <text x="{(label_width + value_width / 2) * 10}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{value}</text>
        <text x="{(label_width + value_width / 2) * 10}" y="140" transform="scale(.1)">{value}</text>
    </g>
</svg>'''
```

---

## Architecture Decisions (Do Not Change These)

### Decision 1: Verifier uses subprocess, not in-process test execution

Always run tests in a subprocess (`subprocess.run(["python", "-m", "pytest", ...])`), never import and run tests in-process. Reasons:
- Mutations modify source files on disk
- In-process execution would pick up the unmutated cached module
- Subprocess ensures the mutated file is actually loaded
- Prevents test pollution between runs

### Decision 2: libcst for ALL file writes, never string manipulation

Never use string concatenation, regex replacement, or `str.replace()` to modify Python files. Always parse with libcst and use CST transformations. This preserves comments, formatting, docstrings, and blank lines exactly.

### Decision 3: Backup-restore is non-negotiable

Every operation that touches a source or test file MUST:
1. Create a backup before writing
2. Validate the new content parses as valid Python (via libcst)
3. Write only if validation passes
4. Restore from backup in `finally` block on ANY exception

No exceptions to this rule. User's codebase is sacred.

### Decision 4: Local-first LLM is a first-class feature

The Ollama provider must work offline with no API keys. Security-conscious teams (fintech, healthcare, enterprise) will not send code to external APIs. `quell fix --llm ollama` must work out of the box if Ollama is running.

### Decision 5: Verification = the moat

The verification loop (apply mutant → run test → confirm kill → restore) is what makes Quell different from every competitor. Do not simplify it, do not skip steps for performance, do not add a `--skip-verification` flag. If verification is slow, optimize the test runner speed, not the verification logic.

---

## What Quell Does NOT Do

These are explicit non-goals. Do not build them:

- **Does not generate tests from scratch for uncovered code** — that's Qodo/Copilot's job. Quell verifies, not generates from nothing.
- **Does not run as a language server** — no LSP protocol. Use MCP for editor integration.
- **Does not do E2E or integration testing** — mutation testing is unit/function level.
- **Does not work on compiled languages** (Java/C#/Go) in v1 — Python first, JS/TS second, everything else later.
- **Does not replace mutation testing tools** — Quell is downstream of mutmut/Stryker, not a replacement.

---

## Test Coverage Requirements

Every module must have tests. Minimum requirements:

| Module | Test file | What to test |
|---|---|---|
| `core/analyzer.py` | `tests/unit/test_analyzer.py` | Each operator classification, edge cases |
| `core/generator.py` | `tests/unit/test_generator.py` | Each rule-based generator, LLM mock |
| `core/verifier.py` | `tests/unit/test_verifier.py` | Verified/fails-on-original/doesnt-kill paths |
| `core/writer.py` | `tests/unit/test_writer.py` | Successful write, failed write + restore |
| `adapters/mutmut_adapter.py` | `tests/adapters/test_mutmut.py` | Mock SQLite DB, parse survivors |
| `adapters/stryker_adapter.py` | `tests/adapters/test_stryker.py` | Sample report JSON |
| `ci/diff_parser.py` | `tests/ci/test_diff_parser.py` | Various git diff formats |
| `score/calculator.py` | `tests/score/test_calculator.py` | Mock SQLite, score calculation |
| `score/badge.py` | `tests/score/test_badge.py` | Green/yellow/red thresholds, valid SVG |
| End-to-end | `tests/integration/test_e2e.py` | Full fix loop on fixture project |

---

## Running the Project

```bash
# Install
pip install uv
uv sync --dev

# Run CLI
uv run quell --help
uv run quell scan
uv run quell fix
uv run quell ci --diff-only
uv run quell score --badge

# Run tests
uv run pytest tests/ -v

# Run MCP server (requires mcp extras)
uv sync --extra mcp
uv run quell-mcp

# Lint + typecheck
uv run ruff check . --fix
uv run mypy quell/
```

---

## Error Messages (UX Standard)

Every error message must:
1. Say what happened
2. Say why it happened
3. Say how to fix it

**Bad:** `FileNotFoundError: .mutmut-cache not found`

**Good:**
```
Error: No mutation testing results found.

Quell needs mutation testing results to work.
Run mutation testing first:

  mutmut run                     # for Python projects
  npx stryker run --reporters=json   # for JS/TS projects

Then run Quell again.
```

Use Rich panels for all error messages:
```python
from rich.panel import Panel
console.print(Panel(
    "[red]Error:[/red] No mutation testing results found.\n\n"
    "Run mutation testing first:\n"
    "  [bold]mutmut run[/bold]\n\n"
    "Then run: [bold]quell scan[/bold]",
    title="Quell",
    border_style="red"
))
```

---

## Competitive Differentiation (Remind Yourself Often)

| Tool | What they do | Quell's edge |
|---|---|---|
| **Qodo/CodiumAI** | Generate tests → achieves coverage | Quell verifies tests catch mutations, not just coverage |
| **GitHub Copilot** | Suggest tests in IDE | Quell proves suggestions work before you commit |
| **Diffblue Cover** | Java-only, RL-based, $2500/dev/year | Python+JS, open core, affordable |
| **mutmut-mcp** | MCP server that runs mutmut | We are downstream: we FIX what mutmut finds |
| **Cursor/Devin** | Generate code + tests autonomously | Quell is the verification layer they're all missing |

The one thing nobody else does: **prove the test kills a specific mutant before writing it to disk**.

---

## Roadmap Phases

**P1 — NOW (current codebase):**
- `quell scan`, `quell fix`, `quell auto` working with mutmut 3.x
- `quell ci --diff-only` for PR pipelines
- `quell score --badge` for README badges

**P2 — :**
- Stryker adapter (JS/TS market, 5x bigger than Python)
- `quell repair` for AI-generated test suites
- `quell-mcp` MCP server

**P3 —:**
- GitHub App (PR comments with verified suggestions)
- VS Code extension (inline mutation score warnings)
- `quell-sdk` stable API

**P4 — :**
- Cloud badge hosting (quell.dev/badge/user/repo)
- Team dashboard (mutation score trends)
- Enterprise: SSO, audit logs, air-gapped mode

**P5 — **
- Autonomous test maintenance (detect when code changes break mutation score, auto-fix)
- PIT adapter (Java)
- IDE-native real-time mutation feedback

---

## Git Commit Convention

```
feat: add quell ci --diff-only for PR pipelines
fix: mutmut 3.x adapter SQLite schema handling
refactor: extract score calculator from ci runner
test: add integration test for full fix loop
docs: update README with badge instructions
```

---

## Questions? Read These First

Before asking "how should I implement X", check:

1. **Verification logic** → `core/verifier.py` — the backup/restore pattern is intentional
2. **Why SQLite directly for mutmut** → mutmut 3.x changed its results API; direct DB access is more stable than parsing CLI output
3. **Why Typer not Click** → async support, better type hints, Pydantic-style validation
4. **Why libcst not ast** → ast is lossy (strips comments, formatting); libcst is lossless
5. **Why subprocess for pytest** → see Architecture Decision 1 above