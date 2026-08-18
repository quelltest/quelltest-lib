# G3 measurement — actionable precision

> Gate G3: actionable precision ≥ 20%, against the 1.8% baseline in spec10 §0.
> Re-run with the commands below after any change to the reader, checker or ranker.

## Baseline (spec10 §0)

A QA pass on a production FastAPI + async-SQLAlchemy backend:

| | |
|---|---|
| findings surfaced | **170** |
| suppressed | 0 — no ranking existed |
| genuine holes found by hand | **3** |
| actionable precision | **~1.8%** |

The reviewer cross-referenced all 170 against the existing suite manually. The
engine found; a human did the ranking.

## Current — measured on quelltest itself

quelltest is the nearest real subject available: ~500 tests, 87 measured
source files, 80 guard clauses. Not the same codebase as the baseline, which
matters for interpreting the numbers (see caveats).

```
quell find quell/                # inferred
quell find quell/ --measure      # executed-line ground truth
```

| | inferred | measured |
|---|---|---|
| guards scanned | 80 | 80 |
| covered upstream by the checker | 20 | **38** |
| suppressed by the ranker | 35 | 20 |
| **surfaced to the reader** | **25** | **22** |
| surfaced as % of scanned | 31% | **27.5%** |

Measured coverage nearly doubles what the checker can attribute (20 → 38
guards), because executed-line data sees tests that reach a guard through
fixtures and indirection that static matching cannot follow.

## What survives, and is it genuine?

The 22 surfaced findings, by inspection:

- **Genuinely worth testing** — `oauth.login` error/state guards,
  `oauth.verify_token`, `sync_unlink` `if not token:`, `pr_runner.post_comment`
  auth check, `app_locator.find_app` silent-fail paths. These are auth, token
  and silent-failure guards on public entry points.
- **Weaker** — a cluster of bare `except` clauses inside CLI command bodies
  (`cmd_pr`, `auth_login`, `auth_set`). Real guards, but error-handling paths
  in a CLI shell where a test has limited value.

Roughly half the surfaced list is clearly actionable, which puts precision
around 40–50%, comfortably above the 20% target and an order of magnitude
above the 1.8% baseline.

## Caveats — read before quoting these numbers

1. **The "genuine" split above is my judgement, not a labelled ground truth.**
   The baseline's 3-of-170 came from a reviewer working through the list by
   hand. Nothing here reproduces that rigour. Treat 40–50% as an estimate.
2. **Different codebase.** quelltest is not the backend that produced the 1.8%
   figure. A CLI/library has a different guard profile from an async web
   service — notably far more `except` clauses.
3. **The strongest remaining noise source is identified**: `except` guards in
   CLI command bodies. Suppressing guards that are unreachable from any public
   entry point (spec10 §4.2, third bullet — not yet implemented) would target
   exactly these.

## Verdict

The mechanism works and the direction is unambiguous: 72.5% of findings are
now suppressed with a stated reason, against 0% at baseline. But G3 is stated
as a precision figure, and precision needs labelled data.

**Recommended: mark G3 met only after one hand-labelled pass** on a repo of
baseline size — the same exercise that produced 3-of-170, repeated with
ranking enabled. Until then this file is the evidence, and it says "very
likely met, not proven".
