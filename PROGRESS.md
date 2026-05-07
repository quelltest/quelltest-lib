# Quell — Implementation Progress

> This file is kept up-to-date after each work session so any AI tool or
> developer can pick up exactly where work left off.

---

## Completed Phases

### P1 — Core (done)

| Feature | Files | Status |
|---------|-------|--------|
| mutmut 3.x adapter | `quell/adapters/mutmut_adapter.py` | ✅ |
| `quell ci` command | `quell/ci/`, `quell/cli.py` | ✅ |
| `quell score` command | `quell/score/`, `quell/cli.py` | ✅ |
| Badge generation | `quell/score/badge.py` | ✅ |
| Score history tracker | `quell/score/tracker.py` | ✅ |
| pyproject.toml v0.2.0 | `pyproject.toml` | ✅ |

### P2 — Extensions (done)

| Feature | Files | Status |
|---------|-------|--------|
| `quell repair` command | `quell/repair/`, `quell/cli.py` | ✅ |
| `quell-mcp` MCP server | `quell/mcp_server.py` | ✅ |
| `quell.sdk.Quell` SDK class | `quell/sdk.py` | ✅ |
| Tests for ci/ and score/ | `tests/ci/`, `tests/score/` | ✅ |

---

## Current Test Coverage

```
105 tests — 0 failures
tests/adapters/   10 tests   mutmut v2+v3 adapter, Stryker adapter
tests/ci/          8 tests   diff_parser (line ranges, multi-hunk, edge cases)
tests/score/      20 tests   calculator (SQLite schema), badge (SVG/color/threshold)
tests/unit/       67 tests   analyzer, generator, verifier, writer
```

Run: `uv run pytest tests/ -v`

---

## Pending Phases

### P3 — Integrations (not started)

- [ ] GitHub App — post PR comments with verified test suggestions
- [ ] VS Code extension — inline mutation score warnings per function
- [ ] `quell-sdk` stable API + PyPI publish as standalone

### P4 — Cloud (not started)

- [ ] Badge hosting at `https://quell.dev/badge/{user}/{repo}`
- [ ] Team dashboard — mutation score trends over time
- [ ] Enterprise: SSO, audit logs, air-gapped mode

### P5 — Autonomous (not started)

- [ ] Auto-detect when code changes break mutation score, auto-fix
- [ ] PIT adapter (Java via XML report)
- [ ] IDE-native real-time mutation feedback (LSP or extension)

---

## Known Limitations / TODOs

- `quell/sdk.py` `verify_test()` has a minor import duplication (`MutmutAdapter`
  imported twice in the async method — harmless but should be cleaned up)
- `quell-mcp` is untested end-to-end (requires `pip install quell[mcp]` and
  a running MCP-compatible agent)
- `quell repair` re-runs mutmut from scratch if no cache exists; on large
  projects this is slow — a `--cache-only` flag would help
- mutmut 3.x does **not** run on Windows without WSL; the adapter handles
  the error gracefully but CI on Windows will return empty survivors

---

## Architecture Invariants (never change these)

1. `verifier.py` — ALWAYS restore source files in a `finally` block
2. `writer.py` — ALWAYS backup before writing, ALWAYS restore on failure
3. `writer.py` — ALWAYS validate CST parse before writing to disk
4. No source code is sent to any server unless an LLM provider is configured
5. LLM is ONLY called for `UNKNOWN` operators — rule engine handles everything else
6. Verification runs in a subprocess (never in-process) so mutations load fresh
