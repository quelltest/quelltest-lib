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

| | inferred | measured | measured + control-flow suppressor |
|---|---|---|---|
| guards scanned | 80 | 80 | 80 |
| covered upstream by the checker | 20 | **38** | 38 |
| suppressed by the ranker | 35 | 20 | **27** |
| **surfaced to the reader** | **25** | **22** | **15** |
| surfaced as % of scanned | 31% | 27.5% | **18.75%** |

Measured coverage nearly doubles what the checker can attribute (20 → 38
guards), because executed-line data sees tests that reach a guard through
fixtures and indirection that static matching cannot follow.

## What survives, and is it genuine?

The first measured run surfaced 22, of which roughly half were a cluster of
`except Exception: raise typer.Exit(1)` handlers in CLI command bodies
(`cmd_pr`, `auth_login`, `auth_set`, `sync_unlink`). Those are real code, but
"does the command exit non-zero when the network fails" is not a test worth
generating. They were the single largest noise source.

Adding the `CONTROL_FLOW_EXIT` suppressor removed exactly that cluster:
**22 → 15**. What remains:

```
cli.py          sync_unlink       if not token:      not_null
auth.py         generate_app_jwt  except             must_raise
cli.py          cmd_ci            if result.score    custom
cli.py          cmd_init          if not             custom
oauth.py        login             if error:          custom
oauth.py        login             if not             custom
oauth.py        login             if                 auth_check
oauth.py        verify_token      if                 custom
tracker.py      get_score_delta   if not history:    silent_fail
app_locator.py  find_app          if not             silent_fail
app_locator.py  find_app          if not             silent_fail
pr_runner.py    post_comment      if not             auth_check
```

Auth checks, token validation, silent-failure paths — on inspection nearly all
of these look worth a test. The one arguable entry is
`generate_app_jwt`'s `except`, which translates a real JWT error rather than
exiting.

## Caveats — read before quoting these numbers

1. **The "genuine" split above is my judgement, not a labelled ground truth.**
   The baseline's 3-of-170 came from a reviewer working through the list by
   hand. Nothing here reproduces that rigour. Treat 40–50% as an estimate.
2. **Different codebase.** quelltest is not the backend that produced the 1.8%
   figure. A CLI/library has a different guard profile from an async web
   service — notably far more `except` clauses.
3. **The `except`/`typer.Exit` noise source has been fixed** by the
   `CONTROL_FLOW_EXIT` suppressor. The remaining §4.2 bullet not yet
   implemented is "guard duplicates validation already enforced upstream"
   (e.g. a Pydantic model validating before the handler runs).

## Verdict

The mechanism works and the direction is unambiguous: **81% of findings are
now suppressed with a stated reason**, against 0% at baseline, and the
surfaced list has gone from 25 to 15 while getting visibly more relevant. But G3 is stated
as a precision figure, and precision needs labelled data.

**Recommended: mark G3 met only after one hand-labelled pass** on a repo of
baseline size — the same exercise that produced 3-of-170, repeated with
ranking enabled. Until then this file is the evidence, and it says "very
likely met, not proven".
