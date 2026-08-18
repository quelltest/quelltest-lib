# Ablation — what each rung of the §4.4 ladder contributes

> `python benchmarks/ablation.py <project>`
> Re-run after any change to the synthesis path.

## Why this shape, not the one #153 specifies

#153 asks for five arms: baseline, trace-carved, mutation-first, CrossHair,
Hypothesis, MCP handoff. **Four of those are unbuilt** — #149 and #150 are still
open, and there are no CrossHair or Hypothesis integrations. A harness that
"compares" unimplemented strategies measures nothing while printing a table
that looks like evidence.

This compares what actually shipped: each rung of the strategy ladder is turned
off in turn against the same project.

| arm | rungs enabled |
|---|---|
| A0 | none — literal stubs only, i.e. pre-spec10 behaviour |
| A1 | + conftest fixtures (#143) |
| A2 | + mined constructions (#144) |
| A3 | + guard-aware mocks (#145) |

Yield counts **verified** tests, not generated ones. A test Gate 5 rejects is
not a contribution.

## Result — tests/fixtures/async_orm_project

```
arm                           gaps   gen  verified   yield    sec
-----------------------------------------------------------------
A0 literal stubs only            4     4         0      0%    3.5
A1 + conftest fixtures           4     4         3     75%    2.8
A2 + mined constructions         4     4         3     75%    2.9
A3 + guard-aware mocks           4     4         3     75%    2.9
```

### What this establishes

**A0 = 0 verified reproduces the original failure exactly.** The 0-for-0 report
in spec10 §0 was not a misconfiguration; it is what the engine did on
async/ORM code before #143.

**#143 does all the work here: 0 → 3.** Reusing the project's own `db_session`
is the single change that moved this fixture.

**#144 and #145 contribute nothing on this fixture — as predicted.** Both PRs
stated that this fixture's parameters are already fixture-covered, so rungs 2
and 3 would not fire. The ablation confirms it rather than leaving it as an
assertion.

### What it does NOT establish

That #144 and #145 are worthless. They target projects with *no* matching
fixture, which this fixture is not. Proving those rungs needs a project whose
parameters no conftest supplies — that fixture does not exist yet and is the
obvious next addition.

A run against quelltest itself (80 guards) would sample a much larger and more
varied population. It is slow, because each arm verifies every gap and
verification injects violations into live source.

## Reading the table honestly

A flat yield across A1–A3 means "these rungs did not fire here", not "these
rungs do not work". Only A0 vs A1 is a difference this fixture can actually
speak to.
