# Quell

**Untested edge cases will bite you in production. Quell finds them before they do.**

[![PyPI](https://img.shields.io/pypi/v/quelltest)](https://pypi.org/project/quelltest/)
[![Python](https://img.shields.io/pypi/pyversions/quelltest)](https://pypi.org/project/quelltest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-quell.buildsbyshashank.tech-blue)](https://quell.buildsbyshashank.tech/docs)

---

```
"I have untested edge cases that are going to bite me in production"
"I don't know which ones they are"
"I don't have time to find them manually"

Quell finds them. Writes tests for the ones it can prove.
Flags the rest with exactly why and where.
```

```bash
pip install quelltest
quell find src/
```

---

## What you get

```
Quell Scan — 23 untested edge cases found

✓ WRITTEN  (8)    Tests generated, passed all 5 gates, ready to ship.
                  → tests/test_payments.py        confidence: 94%  [HIGH]
                  → tests/test_auth.py            confidence: 88%  [HIGH]
                  → tests/test_billing_caps.py    confidence: 72%  [MEDIUM]

⚠ SCAFFOLDED (9)  Test structure written. You finish the assertion.
                  → tests/scaffold/test_billing.py
                  → tests/scaffold/test_user.py

✗ FLAGGED  (6)    Cannot auto-test. Here's why and where.
                  → src/billing.py:142  depends on external API
                  → src/user.py:87     depends on object state

──────────────────────────────────────────────────────────────
PRS  72/100  🟡 Review Needed
Edge case coverage: 73%  |  Avg confidence: 85%
```

---

## How it works

Quell reads guard clauses, docstrings, and Pydantic models that already exist in your code. No annotations required.

Every test candidate passes 5 gates before it's written:

> Every test Quell writes passes 5 gates — syntax, originality, security, runs-on-correct-code, and fails-on-injected-bug. Most AI test tools run one. We run all five. Every test ships with a confidence score so you know what to review and what to merge.

```
Gate 1  AST validity + import check
Gate 2  Originality (no boilerplate, no duplicates)
Gate 3  Security (no eval, no network, no env mutations)
Gate 4  Passes on correct code → proves the test is valid
Gate 5  Fails on violated code → proves the test catches real bugs
         │
         ├── WRITTEN        all 5 passed, written to disk
         ├── SCAFFOLDED     stopped before gate 4, stub written for you
         └── FLAGGED        cannot auto-test, reason + source location given
```

Rule-based engine handles ~75% of cases with no LLM, no network, no code leaving your machine.

---

## Quick start

```bash
pip install quelltest

# Find untested edge cases (no writes)
quell find src/

# Find + write tests for confident cases
quell find src/ --fix

# Skip prompts in CI
quell find src/ --fix --auto

# Set up GitHub Action (posts PRS badge + comment on every PR)
quell install --action
```

---

## Commands

| Command | Description |
|---------|-------------|
| `quell find [PATH]` | Find untested edge cases. `--fix` to write tests. |
| `quell score [PATH]` | Show Production Readiness Score. `--badge` for SVG. |
| `quell reproduce "<bug>"` | Turn a bug description into a failing test (needs auth). |
| `quell ci [PATH]` | CI gate — exits non-zero if PRS below threshold. |
| `quell auth set` | Store LLM API key securely. |
| `quell init` | Add `[tool.quell]` to `pyproject.toml`. |
| `quell install --action` | Write GitHub Actions workflow. |

Full CLI reference: [docs/cli.md](docs/cli.md)

---

## Production Readiness Score

> Quell gives every Python project a Production Readiness Score. One number that tells you how confident your test suite is about your edge cases. Track it in CI, drop it in your README badge, watch it climb.

```bash
quell score src/
# PRS 84/100  🟢 Production Ready
# Edge case coverage: 91%  |  8 WRITTEN · 2 SCAFFOLDED · 1 FLAGGED

quell score src/ --badge   # prints SVG badge for README
```

| PRS | Tier | Meaning |
|-----|------|---------|
| ≥ 80 | 🟢 Production Ready | Ship it |
| 60–79 | 🟡 Review Needed | Some gaps to address |
| < 60 | 🔴 Edge Cases Uncovered | Real risk in production |

---

## Comparison

| | Quell | Copilot | Qodo | Hypothesis |
|---|---|---|---|---|
| Finds edge cases automatically | ✓ | ✗ | ✗ | partial |
| Reads existing specs in your code | ✓ | ✗ | ✗ | ✗ |
| Writes ready-to-run tests | ✓ | ✓ | ✓ | ✗ |
| Validates test passes on correct code | ✓ | ✗ | partial | ✓ |
| Validates test fails on injected bug | ✓ | ✗ | ✗ | ✗ |
| Originality check (no duplicate tests) | ✓ | ✗ | ✗ | ✗ |
| Security check on generated tests | ✓ | ✗ | ✗ | ✗ |
| Per-test confidence score | ✓ | ✗ | ✗ | ✗ |
| Production Readiness Score | ✓ | ✗ | ✗ | ✗ |
| Works offline (no LLM required) | ✓ | ✗ | ✗ | ✓ |
| Your code never leaves your machine | ✓ | ✗ | ✗ | ✓ |

---

<details>
<summary>30-second pitch</summary>

Every codebase has edge cases nobody tested. Maybe it's a guard clause, maybe a Pydantic constraint, maybe a docstring that says "raises ValueError" but no test enforces it. Quell scans your code, finds those gaps, writes pytest tests for the ones it can prove, and flags the rest with exactly where to look. Rule-based, runs offline, your code never leaves your machine.

</details>

---

## What Quell reads

No annotations or special setup — Quell reads specs that already exist in your code:

**Guard clauses**
```python
def process_payment(amount: float) -> dict:
    if amount <= 0:
        raise ValueError(f"Amount must be positive, got {amount}")
```

**Pydantic models**
```python
class PaymentRequest(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal["USD", "EUR", "GBP"]
    description: str = Field(min_length=1, max_length=500)
```

**Docstrings**
```python
def apply_discount(price: float, percentage: float) -> float:
    """
    Apply discount to price.

    Raises:
        ValueError: If percentage not between 0 and 100.
        ValueError: If price is negative.
    """
```

---

## Configuration

```bash
quell init   # adds [tool.quell] to pyproject.toml
```

```toml
[tool.quell]
llm_provider = "groq"              # groq | anthropic | openai | ollama
llm_model    = "llama-3.3-70b-versatile"
use_llm      = false               # opt-in LLM fallback (requires quell auth)
prs_threshold = 60                 # minimum PRS to pass quell ci
scaffold_dir  = "tests/scaffold"   # where SCAFFOLDED stubs go
auto_write    = false
```

LLM is opt-in. Store your key with:
```bash
quell auth set --provider groq --key sk-...
```

---

## Installation

```bash
pip install quelltest
```

Optional extras:
```bash
pip install quelltest[groq]      # Groq LLM fallback
pip install quelltest[pyspark]   # PySpark schema scanning
pip install quelltest[mcp]       # MCP server for AI agents
```

Requires Python 3.11+. Works on Linux, macOS, Windows.

---

## Python SDK

```python
from quell import Quell

q = Quell()
result = q.check("src/")
print(f"PRS: {result.score}  |  Gaps: {len(result.uncovered)}")
```

---

## Development

```bash
git clone https://github.com/quelltest/quelltest-lib.git
cd quelltest-lib
uv sync --dev

uv run pytest tests/ -v
uv run ruff check . --fix
uv run mypy quell/

# Run quell on itself
uv run quell find quell/
```

---

## Links

- **Docs:** [quell.buildsbyshashank.tech/docs](https://quell.buildsbyshashank.tech/docs)
- **How it works:** [docs/how-it-works.md](docs/how-it-works.md)
- **CLI reference:** [docs/cli.md](docs/cli.md)
- **PyPI:** [pypi.org/project/quelltest](https://pypi.org/project/quelltest/)
