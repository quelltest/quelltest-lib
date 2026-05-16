# Quell Documentation

> *Your code says what it should do. Quell proves it.*

Quell finds untested edge cases in Python code and writes proven pytest tests for them.
The engine is rule-based and deterministic — ~75% of cases handled with no LLM, no network,
no code leaving your machine.

**v2.0.0** introduces `quell find`, three-bucket output (WRITTEN / SCAFFOLDED / FLAGGED),
the 5-gate verification pipeline, and the Production Readiness Score (PRS).

## Guides

- [Quick Start](quickstart.md) — install, first run, CI setup
- [How It Works](how-it-works.md) — 5-gate pipeline, confidence scoring, PRS deep-dive
- [CLI Reference](cli.md) — all commands and flags
- [Configuration](configuration.md) — `[tool.quell]` reference
- [GitHub Integration](github-integration.md) — GitHub Actions + PR annotations
- [Changelog](changelog.md) — full release history

## Key concepts

### Two-phase verification (the moat)
Every generated test must:
1. **Pass** on correct code — proves the test is valid
2. **Fail** on violated code — proves the test catches the bug

Only tests that pass both phases are written to disk.

### QuellGraph (v1.0.0)
A persistent SQLite code-intelligence graph at `.quellgraph/graph.db`.
Tracks transitive infra dependencies via BFS across call chains.

```bash
quell graph build src/          # cold build — scans all .py files
quell graph show                # list all functions + infra tags
quell graph why my_func         # explain why a function needs infra
quell graph stale               # list functions affected by recent changes
quell graph stats               # totals: functions, classes, infra-dependent
```

### Ephemeral containers (v1.0.0)
```bash
quell check src/ --with-containers     # auto-start postgres/redis/etc.
quell check src/ --keep-containers     # leave containers running after run
quell teardown                         # stop all quelltest-managed containers
```

Quelltest **never** reads your real `DATABASE_URL` or credentials.
All containers use hardcoded ephemeral credentials and are destroyed after the run.

### Confidence scores (v1.0.0)
Every generated test receives a 0–100 confidence score across 6 factors:
annotation coverage, constraint clarity, dependency clarity, graph coverage,
docstring quality, and mutation strength.

| Tier   | Score | Written? | Runs in CI? |
|--------|-------|----------|-------------|
| HIGH   | ≥ 85  | yes      | yes         |
| MEDIUM | ≥ 70  | yes      | yes         |
| LOW    | ≥ 50  | yes      | no          |
| SKIP   | < 50  | no       | no          |

Override with `--min-confidence N` (write gate) or set `ci_confidence` in `quell.toml`.
