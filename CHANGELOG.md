# Changelog

All notable changes to the `quelltest` Python package (PyPI) are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). Dates are the PyPI upload dates in UTC. Versions that were tagged but never uploaded to PyPI (0.2.0, 0.9.1, 0.9.9, 0.9.9.1) are folded into the next published release.

## Unreleased

Changes on `master` since 2.0.0 that are not on PyPI yet (`pyproject.toml` already says 2.0.1). Entries are written from the merged pull requests; PR numbers are in parentheses.

### Added
- Measured per-line coverage is the ground truth for gaps (#165); gaps are ranked and suppressed by actionability (#167), `quell find` ranks gaps and offers measured coverage (#168), and process-control exits are suppressed (#170).
- Synthesis mines real construction sites for custom types (#162), builds guard-aware mocks for parameters you do not supply (#163), reuses the project's own `conftest.py` fixtures (#157) and generates native async tests instead of `asyncio.run` (#158).
- The verifier classifies gate failures and retries instead of discarding the test (#171).
- MCP server for the Claude connector with OAuth PKCE and 8 tools (#123), and cloud sync with the `quell sync` command and `--sync` flag (#122).
- Benchmarks: an ablation harness for the synthesis ladder (#172) and a recorded measurement of quelltest on itself (#169).

### Changed
- The Production Readiness Score scores the codebase, not quelltest's own output (#156).
- The rule engine types every previously silent skip (#164).
- `quell find` reports verified tests as WRITTEN, uses the real PRS and no longer crashes on Windows (#161).
- Licence: the project is relicensed from MIT to Apache-2.0 (#178; applies from the next release; releases up to 2.0.0 stay MIT).

### Removed
- **Breaking:** `quell scan` and `quell check` are removed and now fail with an error; use `quell find` (#124).

### Fixed
- The verifier runs candidate tests inside the project's test tree (#160).
- Boundary injection no longer corrupts mined constructions (#173); synthesis rung 3 is now actually called and composed with rung 2 (#174).
- Six defects found by adversarial review (#176); CI: the fake self-check is fixed, lint is wider, the synthesis ladder is gated and the CLI contract is pinned (#175); a mis-attributed benchmark claim for rung 1 is retracted and marginal contribution is measured instead (#177).
- `quell find`, the PR comments, the GitHub Action and the environment hints no longer tell you to run the removed `quell scan` / `quell check`; they point to `quell find ... --fix`. The composite `action.yml` was running `quell scan ... || true`, so it silently scanned nothing (#180).
- The docs no longer document a non-existent `quell install --action` flag (the flag is `--pr`) and describe what `quell install` really writes (#181).

## 2.0.0 - 2026-05-16

Three-bucket output, a 5-gate verification pipeline and the Production Readiness Score.

### Added
- `quell find`: new primary command; auto-detects all spec sources; `--fix` writes WRITTEN tests, `--auto` skips confirmation, `--format github` emits CI annotations, `--use-llm` enables the Groq fallback.
- Three-bucket output: WRITTEN (verified, written to disk), SCAFFOLDED (stubs in `tests/scaffold/` with `# quell: complete assertion`), FLAGGED (one-line reason per item; nothing is dropped silently).
- 5-gate pipeline: Gate 1 AST validity, Gate 2 originality, Gate 3 security, Gate 4 passes on correct code, Gate 5 fails on violated code. Only tests that pass all five become WRITTEN.
- Production Readiness Score (PRS): a 0-100 score across WRITTEN tests and confidence values; tiers GREEN at 80 and above, YELLOW at 60 and above, RED below 60; posted as a PR comment by the GitHub Action.
- Groq LLM provider (`llama-3.3-70b-versatile`), configured with `quell auth set --provider groq --key ...`. The LLM is opt-in (`use_llm = false` by default).

### Changed
- `quell init` writes the v2.0.0 defaults (groq, `prs_threshold=60`, `scaffold_dir`) and adds the scaffold directory to `.gitignore`.
- `quell score` is rewritten: it reads the PRS from `quell-report.json`; `--badge` writes an SVG and `--json` prints machine-readable output.

### Upgrade notes
- Requires Python 3.11+. The LLM stays off unless you pass `--use-llm` or set `use_llm = true`.

## 1.0.0 - 2026-05-16

Infrastructure-aware verified testing: QuellGraph and an ephemeral container engine.

### Added
- **QuellGraph:** persistent SQLite code-intelligence graph at `.quellgraph/graph.db`; incremental sha256-based AST builder; BFS infra-tag propagation across call chains (3-hop verified); `quell graph build / show / why / stale / stats`.
- **Container engine:** starts throwaway Docker containers (postgres, redis, localstack, mongo, smtp, rabbitmq, elasticsearch) with hardcoded ephemeral credentials only; keep-alive lockfile; `quell teardown`; pytest fixture injection into `conftest.py`.
- **Confidence scorer:** six factors (annotation coverage, constraint clarity, dependency clarity, graph coverage, docstring quality, mutation strength); tiers HIGH at 85 and above, MEDIUM at 70, LOW at 50, SKIP below 50; a write gate and a CI gate.
- **CLI flags:** `--with-containers`, `--min-confidence`, `--ci-confidence`, `--keep-containers`, `--graph-rebuild`.
- Environment detection for 8 runtime types (LOCAL_DOCKER, GITHUB_ACTIONS, GITLAB_CI, CIRCLECI, DEVCONTAINER, DOCKER_IN_DOCKER, KUBERNETES_POD, NO_DOCKER) with a per-environment strategy.

### Upgrade notes
- No breaking changes: all new flags are opt-in.

## 0.9.9.4 - 2026-05-14

### Fixed
- The engine skips the `value=None` fallback stub and module-level `assert` guards.

## 0.9.9.2 - 2026-05-14

Rolls up the unpublished 0.9.9 and 0.9.9.1, and fixes the release pipeline.

### Fixed
- Engine accuracy: nested function scanning, syntax fixes, bare `return` violation, `silent_fail` stubs.
- CI: ruff E501, mypy `arg-type` and `no-untyped-def` fixes.
- Release workflow publishes with `pypa/gh-action-pypi-publish`.

## 0.9.8 - 2026-05-12

### Added
- GitHub Action: a composite action that scans PRs, posts inline annotations and an idempotent PR comment; `fail-on-gaps: true` blocks merges.
- GitHub App rewrite: webhook server with no per-repo YAML; fetches changed files via the Contents API.
- `--format github` flag that outputs GitHub Actions annotation syntax.

### Changed
- `source_line` added to the `Requirement` model.

## 0.9.7 - 2026-05-14

Uploaded to PyPI on 2026-05-14, after 0.9.8 (the code dates from 2026-05-12).

### Fixed
- Functions whose required parameters are all of unknown type are skipped before any test is generated, so they no longer produce guaranteed-failing stubs.

## 0.9.6.1 - 2026-05-12

### Added
- CUSTOM guard rules: `assert` statements now generate concrete stubs.

### Changed
- Concrete class preference: non-abstract implementors are picked over base classes.
- Assert violation injection comments out the `assert` line for Phase 2.

## 0.9.6 - 2026-05-14

Uploaded to PyPI on 2026-05-14, after 0.9.8 (the code dates from 2026-05-12).

### Fixed
- Written tests go to the project root `tests/` directory (found via `pyproject.toml`, `setup.py`, `setup.cfg` or `.git`), not `src/tests/`; the CLI prints the full path.

## 0.9.5 - 2026-05-12

### Added
- Builtin exception guard: `ValueError`, `TypeError` and similar are handled directly.

### Changed
- Abstract stubs are skipped; ABC classes are never instantiated.

### Fixed
- `PYTHONPATH=src/` is set automatically in the pytest subprocess, which fixes src-layout projects.

## 0.9.4 - 2026-05-12

### Added
- Detects `try/except/raise` patterns and generates `must_raise` tests.
- Detects standalone `raise` statements in guard branches.

## 0.9.3 - 2026-05-12

### Fixed
- pytest is auto-detected when it is not in the `sys.executable` environment (conda, venv, pipx).

## 0.9.2 - 2026-05-11

Includes the unpublished 0.9.1.

### Added
- Auto-loads the `.env` family (`.env`, `.env.example`, `.env.template`, `.env.local`, `.env.secrets`) into the pytest subprocess, so tests no longer fail on missing environment variables.

### Changed
- The report surfaces the real failure reason (from pytest output) for rejected tests.

## 0.9.0 - 2026-05-11

Dual-engine architecture.

### Added
- Dual-engine architecture: the rule engine handles known patterns deterministically; the framework engine handles FastAPI and Flask route guards.

## 0.8.1 - 2026-05-11

### Fixed
- The pytest subprocess uses `sys.executable` instead of a hardcoded `python`, so it runs in the same environment as Quell.
- Subprocess output is decoded as UTF-8, which fixes silent errors on Windows (cp1252).

## 0.8.0 - 2026-05-11

Async support and full violation coverage.

### Added
- Full violation coverage: every `ConstraintKind` gets a targeted injection.
- Async function support: the test body is wrapped in `asyncio.run()`.

### Fixed
- Windows encoding root cause in the verifier.
- Duplicate kwargs in `not_null` stubs.

## 0.7.0 - 2026-05-11

### Fixed
- Duplicate kwargs in `not_null` stubs.
- `silent_fail` verification now correctly tests `None`-return paths.

## 0.6.9 - 2026-05-10

### Fixed
- Pydantic `@classmethod` validators are handled correctly in stubs.
- Enum kwarg name: stubs use the correct field name.
- Duplicate `Optional[X]` in generated code is removed.

## 0.6.8 - 2026-05-10

### Fixed
- Async functions are skipped, which was the root cause of `verified=0` on FastAPI backends. Async support arrives in 0.8.0.

## 0.6.7 - 2026-05-10

### Fixed
- A word-boundary check removes false stub injections on FastAPI endpoints.

## 0.6.6 - 2026-05-10

### Fixed
- 104 false rejections caused by stub generation bugs.

## 0.6.5 - 2026-05-10

### Added
- `quell-report.json` is written after every run.

### Fixed
- Smarter stubs; guards on `self.attr` are skipped.

## 0.6.4 - 2026-05-10

### Changed
- `quell scan --fix` is rule-engine-only by default, so it no longer hangs on an LLM call.

## 0.6.3 - 2026-05-10

### Fixed
- `quell scan` runs fully synchronously, which removes `asyncio.run()` event loop conflicts.

## 0.6.2 - 2026-05-10

### Fixed
- Asyncio event loop conflict: the scan always runs in a dedicated thread (Jupyter and IPython).

## 0.6.1 - 2026-05-10

### Changed
- Packaging only: adds `twine` to the dev dependency group. No behaviour changes.

## 0.6.0 - 2026-05-10

CodeGuardReader.

### Added
- CodeGuardReader: scans `if`/`raise`, `assert` and `try`/`except`/`raise` patterns directly from source; no docstrings or annotations needed.
- `quell scan` command, which works on any Python file.
- FixSuggester: interactive fix recommendations.

## 0.5.1 - 2026-05-09

### Fixed
- `quell auth login` no longer hangs: `Connection: close` header and a faster token error.

## 0.5.0 - 2026-05-09

Auth and PySpark.

### Added
- Auth system: `quell auth login` with PKCE OAuth; credentials are stored in `~/.quell/credentials.json`. `QUELL_API_KEY` for CI.
- PySpark reader: extracts requirements from `StructType` schemas (`nullable=False`, `DoubleType`, and so on) without importing pyspark; install with `pip install quelltest[pyspark]`.
- `quell pr`: posts scan results as a GitHub PR comment.
- `--no-llm` flag: disables all LLM calls; rule engine only.

## 0.4.4 - 2026-05-08

### Changed
- Rule engine improvements: better boundary detection and improved stub generation.

## 0.4.3 - 2026-05-08

### Added
- `--version` / `-V` flag on the CLI.

### Fixed
- `__version__` reported the wrong version.

## 0.4.2 - 2026-05-08

### Changed
- Targeted violation injection: each `ConstraintKind` gets a precise mutation.
- Tests for optional-return functions are skipped.

## 0.4.1 - 2026-05-08

### Added
- Signature inspection: real parameter names and types are used in generated stubs, and real tests are generated.
- Diagnostic report: `quell-report.json` records per-requirement outcomes.

## 0.4.0 - 2026-05-08

Spec-first architecture.

### Changed
- Unified `Requirement` model: every spec reader returns `list[Requirement]`.

## 0.3.0 - 2026-05-07

GitHub integration and PyPI packaging. Includes the unpublished 0.2.0.

### Added
- GitHub integration: PR comment poster and webhook listener (optional `github` extra, `quell-github-app` entry point).
- VS Code extension scaffold.
- CI score tracking: `quell score --badge` generates a badge (from 0.2.0).
- Repair mode: auto-writes verified tests to disk (from 0.2.0).
- MCP server: exposes quelltest as a tool for Claude Desktop (optional `mcp` extra, from 0.2.0).
- SDK: `from quell import Quell; q = Quell(); q.check('src/')` (from 0.2.0).

## 0.1.0 - 2026-05-07

Initial release.

### Added
- Python 3.11+, Typer CLI, Pydantic v2 and libcst.
- Docstring reader: extracts `Raises:` and `Returns:` blocks.
- Pydantic reader: extracts `Field` constraints and `Literal` types.
- Two-phase verifier: Phase 1 must pass on correct code, Phase 2 must fail on violated code.
- AST-safe writer: libcst injection, backup before write, restore on failure.
