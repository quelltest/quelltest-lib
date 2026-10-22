# CLI Reference — Quell v2.0.0

## Command Summary

| Command | Description |
|---------|-------------|
| `quell find [PATH]` | Find untested edge cases. `--fix` to write tests. |
| `quell score [PATH]` | Show edge case coverage score. |
| `quell reproduce "<bug>"` | Turn a bug description into a failing test (requires LLM auth). |
| `quell ci [PATH]` | CI mode. Exits non-zero if PRS below threshold. |
| `quell auth` | Manage LLM API keys. Subcommands: `set`, `status`, `logout`. |
| `quell init` | Set up `[tool.quell]` block in `pyproject.toml`. |
| `quell install` | Install GitHub Action workflow or pre-commit hook. |

---

## `quell find`

Find untested edge cases in Python source files.

```bash
quell find [PATH] [OPTIONS]
```

**Arguments**

| Name | Default | Description |
|------|---------|-------------|
| `PATH` | `.` | File or directory to scan |

**Options**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--fix` | bool | false | Write tests for confident cases (WRITTEN bucket) |
| `--auto` | bool | false | Skip confirmation prompts (for CI) |
| `--use-llm` | bool | false | Enable LLM fallback for complex cases (requires `quell auth`) |
| `--root PATH` | path | `.` | Project root for coverage checking and report output |
| `--format / -f` | str | `console` | Output format: `console` or `github` |

**Examples**

```bash
quell find src/                    # find all untested edge cases
quell find src/ --fix              # find + write tests for confident cases
quell find src/ --fix --auto       # skip prompts (use in CI)
quell find src/ --fix --use-llm    # enable LLM for harder cases
quell find src/ --format github    # GitHub Actions annotation format
```

**Output buckets**

```
✓ WRITTEN  (8)    Tests generated, passed 5/5 gates, ready to ship.
                  → tests/test_payments.py        confidence: 94%  [HIGH]

⚠ SCAFFOLDED (9)  Test structure written. You finish the assertion.
                  → tests/scaffold/test_billing.py

✗ FLAGGED  (6)    Cannot auto-test. Here's why.
                  → src/billing.py:142  depends on external API
```

---

## `quell score`

Show the Production Readiness Score (PRS) for a path.

```bash
quell score [PATH] [OPTIONS]
```

**Options**

| Flag | Description |
|------|-------------|
| `--badge` | Output an SVG badge string to stdout |
| `--json` | Output score as JSON |

---

## `quell reproduce`

Turn a natural language bug description into a failing pytest test.

```bash
quell reproduce "<bug description>" [OPTIONS]
```

Requires LLM auth (`quell auth set --provider groq --key sk-...`).

```bash
quell reproduce "payment accepts zero amount"
quell reproduce "discount rounds incorrectly for 33.33%"
```

---

## `quell ci`

CI mode: scan and exit non-zero if PRS falls below the configured threshold.

```bash
quell ci [PATH] [OPTIONS]
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold INT` | 60 | Minimum PRS to pass (overrides `prs_threshold` in config) |
| `--root PATH` | `.` | Project root |

Exit codes: `0` = PRS at or above threshold, `1` = PRS below threshold, `2` = error.

---

## `quell auth`

Manage LLM API keys stored in the OS keyring (or encrypted config fallback).

```bash
quell auth set --provider groq --key sk-...    # store key
quell auth status                              # show stored providers
quell auth logout --provider groq             # remove key
```

**Subcommands**

| Subcommand | Description |
|------------|-------------|
| `set` | Store an API key for a provider |
| `status` | Show which providers have stored keys |
| `logout` | Remove a stored key |

**Supported providers**: `groq`, `anthropic`, `openai`

---

## `quell init`

Add the `[tool.quell]` configuration block to `pyproject.toml`.

```bash
quell init
```

Creates the block with all default values. Safe to run on an existing project — skips if the block already exists.

---

## `quell install`

Install integrations. With no flags, installs both.

```bash
quell install --pr      # write .github/workflows/quell.yml
quell install --hook    # add Quell to .pre-commit-config.yaml
quell install           # both
```

**Options**

| Flag | Description |
|------|-------------|
| `--pr` | Write a GitHub Actions workflow that runs `quell find --format github` and posts a PRS comment |
| `--hook` | Add a pre-commit hook entry to `.pre-commit-config.yaml` |

---

## Removed Commands

The following commands were removed in v1.2. They now exit with an error telling you to use `quell find`:

| Removed | Replacement |
|---------|-------------|
| `quell scan` | `quell find` |
| `quell check` | `quell find` |
