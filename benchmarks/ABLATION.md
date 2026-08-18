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

## Result — quelltest itself (84 gaps)

```
arm                           gaps   gen  verified   yield    sec
-----------------------------------------------------------------
A0 literal stubs only           84    49        20     24%  165.1
A1 + conftest fixtures          84    49        20     24%  164.5
A2 + mined constructions        84    49        20     24%  168.6
A3 + guard-aware mocks          84    49        20     24%  164.7
```

**Every arm is identical. The ladder contributes nothing on this codebase.**

That is a real result and it should not be explained away. What it says:

- quelltest is a library and CLI. Its guards take paths, strings, ints and
  flags — types the literal stubs in `sig_inspector` already handle, which is
  why the A0 baseline already reaches 24%.
- It has no `db_session`-style fixtures whose names match function parameters,
  so rung 1 never fires. Nothing constructs domain objects with literal
  arguments, so rung 2 never fires. Few guards read an attribute off a complex
  parameter, so rung 3 never fires.

The ladder was built for the async/ORM web-service shape described in
spec10 §0. On that shape it takes yield 0% → 75%. On library-shaped code it is
inert — neither helping nor hurting (runtime is flat across arms, so the
discovery passes cost nothing measurable).

## Reading these tables honestly

A flat yield across A1–A3 means "these rungs did not fire here", not "these
rungs do not work". Only A0 vs A1 on the async fixture is a difference these
runs can actually speak to.

**The measured evidence for the whole §4.4 ladder is currently: 0 → 3 verified
tests on one 4-guard fixture.** That is thin. It is consistent with the
production report in spec10 §0 that motivated the work, and the A0 = 0 result
reproduces that failure exactly — but one small fixture is not a benchmark.

What would strengthen it, in order:

1. A second async/ORM fixture with *no* matching conftest fixtures, so rungs 2
   and 3 have a chance to fire at all. Neither has yet been observed doing
   anything on any project.
2. A real third-party async backend, which is the population spec10 §0 came
   from.
