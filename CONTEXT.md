# Quell — AI Handoff Context

> Read this before touching any code. It covers what Quell is, how the
> codebase is structured, every key design decision, and where the sharp
> edges are. Written for AI tools and developers picking up mid-session.

---

## What Quell Is (One Sentence)

**Quell is the verification layer for AI-generated tests — it proves every
test actually catches real bugs, not just achieves coverage.**

Every other tool (Qodo, Copilot, Cursor) generates tests that look green
but are weak. Quell uses mutation testing as a proof engine: if a test
doesn't kill a mutant, it doesn't count.

```
Every other tool:   LLM → test → ✓ green (coverage achieved, but weak)
Quell:              LLM → test → prove it kills a mutant → ✓ actually strong
```

---

## Repository Layout

```
quell/
├── cli.py                   ← all Typer CLI commands (scan, fix, auto, ci, score, repair, report, init)
├── sdk.py                   ← clean programmatic API (Quell class)
├── mcp_server.py            ← MCP server for AI agents (Claude Code, Cursor, Devin)
├── core/
│   ├── models.py            ← all Pydantic models — source of truth for data shapes
│   ├── analyzer.py          ← classifies mutation operator from AST diff
│   ├── generator.py         ← rule-based test generators + LLM fallback
│   ├── verifier.py          ← THE MOAT: apply mutant → run test → confirm kill → restore
│   └── writer.py            ← libcst-based test file injection (lossless)
├── adapters/
│   ├── base.py              ← MutationAdapter protocol
│   ├── mutmut_adapter.py    ← mutmut 3.x (SQLite) + 2.x (CLI) auto-detect
│   └── stryker_adapter.py   ← Stryker JSON report parser
├── ci/
│   ├── diff_parser.py       ← git diff → changed line ranges (for --diff-only)
│   ├── runner.py            ← runs mutmut programmatically (full or targeted)
│   ├── threshold.py         ← score threshold check + exit code logic
│   └── reporter.py          ← console / JSON / GitHub Actions output
├── score/
│   ├── calculator.py        ← reads .mutmut-cache SQLite → ProjectScore / FileScore
│   ├── badge.py             ← generates shields.io-style SVG badge
│   └── tracker.py           ← appends score snapshots to .quell/history.json
├── repair/
│   └── engine.py            ← RepairEngine: runs mutmut + fix loop internally
├── llm/
│   ├── client.py            ← LLMClient abstract base + factory
│   ├── prompts.py           ← test generation prompt builder
│   └── providers/
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       └── ollama_provider.py   ← local/offline, no API key needed
└── ui/
    ├── console.py           ← Rich Console singleton
    ├── progress.py
    └── diff.py
```

---

## Data Flow (end to end)

```
mutmut run  →  .mutmut-cache (SQLite)
                    ↓
            MutmutAdapter.read_survivors()
                    ↓
            [SurvivedMutant, ...]          ← Pydantic models
                    ↓
            MutationAnalyzer.analyze()
              • classifies operator
              • finds enclosing function
              • finds test file
                    ↓
            TestGenerator.generate()
              • rule-based for 9 operators
              • LLM fallback for UNKNOWN
                    ↓
            MutantVerifier.verify()        ← THE CRITICAL PATH
              1. run pytest on original    → must PASS
              2. apply mutant to disk
              3. run pytest on mutated     → must FAIL
              4. restore source (finally)
                    ↓
            TestWriter.write()
              • backup source
              • parse with libcst
              • inject test function
              • validate parse
              • write to disk
              • append to audit log
```

---

## Key Models (`quell/core/models.py`)

| Model | Purpose |
|-------|---------|
| `SurvivedMutant` | A mutant your tests missed. Core unit of work. |
| `GeneratedTest` | Candidate test function. Has `test_code`, `test_file_path`. |
| `VerificationResult` | Outcome of running the test vs the mutant. |
| `VerificationStatus` | `verified` / `fails_on_original` / `doesnt_kill_mutant` / `syntax_error` / `timeout` / `equivalent_mutant` |
| `QuellConfig` | Loaded from `[tool.quell]` in pyproject.toml. Passed everywhere. |
| `AuditEntry` | Immutable record written to `.quell/audit.jsonl` after every action. |

---

## mutmut Adapter — Version Detection

`MutmutAdapter` (`quell/adapters/mutmut_adapter.py`) auto-detects mutmut version:

```python
def _is_mutmut3(self) -> bool:
    # mutmut 3.x uses MutantStatus table; 2.x uses mutant table
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return "MutantStatus" in {t[0] for t in tables}
```

- **v3.x path**: queries `MutantStatus WHERE status = 'survived'`, then calls
  `mutmut show <id>` for each survivor to get the diff
- **v2.x path**: calls `mutmut results` CLI + `mutmut show <id>` (original behaviour)
- **no cache**: shows a Rich error panel and returns `[]`
- **Windows**: mutmut 3.x requires WSL on Windows; adapter handles gracefully

---

## CI Mode — `--diff-only` (the killer feature)

Full mutation testing takes 15-30 min. `quell ci --diff-only` gets it to 2-3 min:

1. `git diff --unified=0 origin/main...HEAD` → `ChangedLines` per file
2. Pass modules to `mutmut run <module.path>` (targeted, not full project)
3. Run fix loop on survivors only in changed files
4. Check threshold, emit JSON/console/GitHub Actions output

Implementation: `quell/ci/diff_parser.py` + `quell/ci/runner.py`

---

## Score Module

`quell/score/calculator.py` reads `.mutmut-cache` and produces:
- `FileScore` — per-file: total/killed/survived mutants, score (0.0–1.0), grade (A/B/C/F)
- `ProjectScore` — weighted aggregate across all files

`quell/score/badge.py` generates shields.io-style SVG:
- Green (`#4c1`) if ≥ 80%
- Yellow (`#dfb317`) if 60–79%
- Red (`#e05d44`) if < 60%

`quell/score/tracker.py` appends JSON snapshots to `.quell/history.json` so
`quell score --compare` can show deltas.

---

## MCP Server (`quell/mcp_server.py`)

Exposes 4 tools to AI coding agents:

| Tool | What it does |
|------|-------------|
| `verify_test(test_code, source_file)` | Proves a test kills at least one mutant |
| `get_survivors(source_file)` | Lists surviving mutants for a file |
| `generate_killing_test(mutant_id, source_file)` | Generates + verifies a killing test |
| `get_quell_score(file_path?)` | Returns current mutation score |

Run: `uvx quell-mcp` (requires `pip install quell[mcp]`)

---

## SDK (`quell/sdk.py`)

```python
from quell import Quell

q = Quell()                            # reads pyproject.toml config
q = Quell(llm="ollama", local=True)   # fully local

result = q.verify_test("def test_foo(): ...", "src/utils.py")
score  = q.get_score()
fixes  = q.fix_all(auto_write=True)
repair = q.repair(Path("tests/"), Path("src/"))
```

---

## CLI Commands

```bash
quell scan                         # list surviving mutants
quell fix                          # interactive fix loop
quell auto                         # batch auto-fix (no prompts)
quell ci                           # CI/CD pipeline
quell ci --diff-only               # PR mode: only changed lines
quell ci --threshold 0.80          # fail if score < 80%
quell ci --report json             # JSON output for dashboards
quell score                        # per-file score table
quell score --badge                # write .quell/badge.svg
quell score --format json
quell repair tests/                # repair AI-generated test suites
quell repair tests/ --show-only
quell report                       # audit log
quell init                         # add [tool.quell] to pyproject.toml
quell-mcp                          # start MCP server
```

---

## Configuration (`[tool.quell]` in pyproject.toml)

```toml
[tool.quell]
llm_provider = "anthropic"           # "anthropic" | "openai" | "ollama"
llm_model = "claude-sonnet-4-6"
max_verification_attempts = 3
verification_timeout_seconds = 30
auto_write = false
```

LLM env vars (only needed for UNKNOWN operators):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
# or run Ollama locally — no API key needed
```

---

## Adding a New Mutation Operator

1. Add enum value to `MutationOperator` in `quell/core/models.py`
2. Add classification logic to `_classify_operator` in `quell/core/analyzer.py`
3. Add generator method `_generate_<operator>_test` in `quell/core/generator.py`
4. Add route in `generate()` in `quell/core/generator.py`
5. Add tests in `tests/unit/test_generator.py`

## Adding a New Mutation Adapter (e.g. PIT for Java)

1. Create `quell/adapters/pit_adapter.py` implementing `MutationAdapter` protocol
2. Add it to `_get_adapter()` in `quell/cli.py`
3. Add integration tests in `tests/adapters/test_pit_adapter.py`

---

## Non-Goals (do not build)

- Do NOT generate tests from scratch for uncovered code (that's Copilot's job)
- Do NOT implement LSP — use MCP for editor integration
- Do NOT work on compiled languages in v1 (Python first, JS/TS second)
- Do NOT replace mutmut/Stryker — Quell is downstream, not a replacement
- Do NOT add `--skip-verification` — verification is the moat

---

## Development

```bash
uv sync --dev
uv run pytest tests/ -v           # 105 tests
uv run ruff check . --fix
uv run mypy quell/
uv run quell --help
```
