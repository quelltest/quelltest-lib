# Quick Start

## Prerequisites

- Python 3.11+

## Installation

```bash
pip install quelltest
```

## Step 1: Find untested edge cases

Point `quell find` at your source directory. It reads guard clauses, docstrings, and Pydantic models, then shows which edge cases have no test.

```bash
quell find src/
```

Example output:

```
Quell Scan — reading guard clauses in 12 file(s)

✓ WRITTEN  (8)    Tests generated, passed 5/5 gates, ready to ship.
                  → tests/test_payments.py        confidence: 94%  [HIGH]
                  → tests/test_auth.py            confidence: 88%  [HIGH]
                  → tests/test_billing_caps.py    confidence: 72%  [MEDIUM]

⚠ SCAFFOLDED (9)  Test structure written. You finish the assertion.
                  → tests/scaffold/test_billing.py
                  → tests/scaffold/test_user.py

✗ FLAGGED  (6)    Cannot auto-test. Here's why.
                  → src/billing.py:142  depends on external API
                  → src/user.py:87     no violation injectable

─────────────────────────────────────────────────────
PRS  72/100  🟡 Review Needed
Edge case coverage: 73%  |  Avg confidence: 85%
```

## Step 2: Write the tests

Add `--fix` to write WRITTEN tests to disk:

```bash
quell find src/ --fix
```

Add `--auto` to skip the confirmation prompt (use in CI):

```bash
quell find src/ --fix --auto
```

## Step 3: Set up CI with a PRS badge

Install the GitHub Action:

```bash
quell install --action
```

This writes `.github/workflows/quelltest.yml`. On every PR it runs `quell find --format github`, posts inline annotations on untested lines, and comments a PRS summary.

Or add the action directly to your workflow:

```yaml
- name: Quell edge case scan
  uses: quelltest/quelltest-lib@v2.0.0
  with:
    source-dir: src/
```

## Step 4: Optional — LLM fallback for harder cases

~75% of edge cases are handled with no network calls. For the rest, enable LLM fallback via Groq (fast, cheap):

```bash
quell auth set --provider groq --key sk-...
quell find src/ --fix --use-llm
```

## Configuration

Run `quell init` to add the default config block, or add it manually:

```toml
[tool.quell]
llm_provider = "groq"
llm_model = "llama-3.3-70b-versatile"
prs_threshold = 60        # minimum PRS to pass quell ci
scaffold_dir = "tests/scaffold"
use_llm = false           # opt-in LLM fallback
auto_write = false
```

See [configuration reference](configuration.md) for all options.
