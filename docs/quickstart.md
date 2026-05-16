# Quick Start

## Prerequisites

- Python 3.11+
- Docker Desktop (optional — only needed for `--with-containers`)

## Installation

```bash
pip install quelltest
```

## Step 1: Run quell check

Point `quell check` at your source directory. It reads docstrings, Pydantic models,
and PySpark schemas, generates verified pytest tests, and writes only those that pass
two-phase verification.

```bash
quell check src/
```

Add `--fix` to write verified tests to disk automatically:

```bash
quell check src/ --fix
```

## Step 2: Build the code-intelligence graph (v1.0.0)

QuellGraph scans your project AST and tracks transitive infrastructure dependencies.
Run once; subsequent builds are incremental (only changed files re-parsed).

```bash
quell graph build src/
quell graph show              # list functions and their infra tags
quell graph why process_payment   # explain infra dependency chain
```

## Step 3: Run with infrastructure containers (v1.0.0)

If your functions depend on postgres, redis, or other infrastructure, pass
`--with-containers` to auto-start throwaway Docker containers:

```bash
quell check src/ --with-containers --fix
```

Quelltest uses only hardcoded ephemeral credentials — your real `DATABASE_URL`
is never read. Containers are torn down automatically after the run.

To stop containers manually:

```bash
quell teardown
```

## Step 4: Filter by confidence score (v1.0.0)

Each generated test receives a 0–100 confidence score. Use `--min-confidence`
to control which tests are written:

```bash
quell check src/ --fix --min-confidence 70   # write only MEDIUM+ tests
quell check src/ --fix --min-confidence 85   # write only HIGH tests
```

## Step 5: Set up CI

```bash
quell install --pr   # writes .github/workflows/quelltest.yml
```

Or use the composite action directly in your workflow:

```yaml
- uses: shashank7109/quelltest_lib@v1.0.0
  with:
    source-dir: src/
    fail-on-gaps: 'true'
    min-confidence: '70'
```

## Configuration

Add `[tool.quelltest]` to your `pyproject.toml`:

```toml
[tool.quelltest]
llm_provider = "anthropic"        # or "ollama" for local
llm_model = "claude-sonnet-4-5"
auto_write = false
score_threshold = 0.0
ci_confidence = 70                # minimum confidence to run in CI
```

Or create `quell.toml` in your project root with the same keys.
