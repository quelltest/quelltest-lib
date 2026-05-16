# How Quell Works — Technical Deep-Dive

## Overview

Quell finds untested edge cases in Python code and writes proven pytest tests for them. The engine is rule-based and deterministic — no LLM, no network, no code leaves your machine unless you explicitly opt in.

```
SOURCE CODE
    │
    ▼
SPEC READERS          read guard clauses, docstrings, Pydantic models
    │
    ▼
REQUIREMENTS          list[Requirement] — one per testable constraint
    │
    ▼
COVERAGE CHECKER      AST-scan test files → mark covered / uncovered
    │
    ▼
TEST SYNTHESIS        rule engine → deterministic test code per constraint kind
    │
    ▼
5-GATE PIPELINE       proves the test is correct before writing it
    │
    ├── WRITTEN        all 5 gates passed, test written to disk
    ├── SCAFFOLDED     stopped at gate 1-3, structure written for human
    └── FLAGGED        cannot auto-test, reason given with source location
```

## Spec Readers

Quell reads specifications that already exist in your codebase — no annotations required.

| Reader | What it reads | Example constraints |
|--------|--------------|-------------------|
| `CodeGuardReader` | `if`/`raise` guard clauses | `if amount <= 0: raise ValueError` |
| `DocstringReader` | `Raises:` / `Returns:` / `Args:` blocks | `Raises: ValueError if amount is zero` |
| `TypeReader` | Pydantic `Field` constraints, `Literal` types | `amount: float = Field(gt=0)` |
| `BugReader` | Natural language bug descriptions | `quell reproduce "accepts zero amount"` |

Every reader returns `[]` on error — they never raise.

## 5-Gate Verification Pipeline

Every generated test candidate passes through five sequential gates before it is written to disk. A gate failure stops the pipeline and routes the result to SCAFFOLDED or FLAGGED.

```
Gate 1 — AST Validity
  ├── Parse the generated test with ast.parse()
  ├── Check all imports resolve (stdlib / installed packages)
  └── FAIL → FLAGGED (reason: INVALID_SYNTAX)

Gate 2 — Originality
  ├── Reject boilerplate-only assertions (assert result is not None)
  ├── Reject tests whose function name already exists in test files
  └── FAIL → test rejected, not written, not scaffolded

Gate 3 — Security
  ├── Reject eval(), exec(), os.system(), subprocess(shell=True)
  ├── Reject unmocked network calls (requests.get, httpx.get)
  ├── Reject hardcoded credentials and os.environ mutations
  └── FAIL → FLAGGED (reason: SECURITY)

Gate 4 — Passes on Correct Code
  ├── Run test in subprocess against the original (unmodified) source
  ├── Test MUST PASS — if it fails, it's a false positive
  └── FAIL → FLAGGED (reason: GATE4_FAILURE)

Gate 5 — Fails on Violated Code
  ├── Inject a violation into a temp copy of the source
  ├── Run test against the violated source
  ├── Test MUST FAIL — if it passes, it can't catch real bugs
  └── FAIL → FLAGGED (reason: GATE5_FAILURE)
```

Gate 1-3 failures can still produce a SCAFFOLDED output — the test structure is written with a `# TODO:` placeholder so a human can finish the assertion. Gate 4-5 failures produce FLAGGED with a precise one-line reason.

Source files are **always restored** in a `finally` block after gate 5 — no matter what happens.

## Three-Bucket Output

Every edge case ends up in exactly one bucket:

| Bucket | Meaning | What you get |
|--------|---------|--------------|
| **WRITTEN** | All 5 gates passed | Ready-to-run pytest test, written to disk |
| **SCAFFOLDED** | Stopped before gate 4 | Test file with `# TODO: add assertion` |
| **FLAGGED** | Cannot auto-test | Source location + one-line reason |

"Flagged" is not failure — it means Quell found an edge case it can't safely auto-test. You know exactly where to look.

## Confidence Scoring

Each WRITTEN test receives a 0–100 confidence score based on four factors (spec7 §2.5):

| Factor | Max pts | What it measures |
|--------|---------|-----------------|
| Spec source quality | 35 | How rich is the spec? (`DOCSTRING_RAISES` > `CODE_GUARD`) |
| Violation specificity | 25 | How precise is the injected violation? |
| Assertion strength | 25 | Does the test assert a specific value or just `is not None`? |
| Coverage uniqueness | 15 | Is this requirement not already covered by existing tests? |

Tiers: **HIGH** ≥ 85 · **MEDIUM** 60–84 · **LOW** < 60

## Production Readiness Score (PRS)

The PRS is a 0–100 project-level metric (spec7 §2.6):

```
PRS = (Σ confidence_of_WRITTEN_tests) / (total_edge_cases × 100) × 100

Modifiers:
  +5  if every FLAGGED item has a # quell: flagged justification comment
  -10 if any HIGH-confidence test has been manually disabled (@pytest.mark.skip)
```

| PRS | Tier | Meaning |
|-----|------|---------|
| ≥ 80 | 🟢 green | Production Ready |
| 60–79 | 🟡 yellow | Review Needed |
| < 60 | 🔴 red | Edge Cases Uncovered |

## Writer Safety

Tests are written using libcst (Concrete Syntax Tree), never string concatenation:

1. Backup source file to `.quell/backups/`
2. Parse existing test file into CST
3. Inject new test function node
4. Validate the modified CST parses correctly
5. Write to disk — or restore backup on any failure

Every write is recorded in `.quell/audit.jsonl`.

## LLM Fallback

The LLM is opt-in and used only when the rule engine cannot handle a constraint kind. Enable with:

```bash
quell find src/ --fix --use-llm   # requires quell auth set --provider groq --key sk-...
```

~75% of edge cases are handled by the deterministic rule engine with no network calls.
