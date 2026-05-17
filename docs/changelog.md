# Changelog

Full release history. All dates UTC. Source on [GitHub](https://github.com/quelltest/quelltest-lib).

---

## v2.0.0 — 2026-05-17 · Three-Bucket Output + Production Readiness Score

**`quell find` — new primary command**
- Replaces `quell check` as the recommended entry point
- Auto-detects all spec sources: docstrings, Pydantic models, PySpark schemas, guard clauses
- `--fix` writes WRITTEN tests; `--auto` skips confirmation (CI); `--format github` for annotations
- `--use-llm` enables Groq fallback for harder cases

**Three-bucket output**
- WRITTEN — tests that passed all 5 gates, written to disk
- SCAFFOLDED — stubs written to `tests/scaffold/test_<module>.py` with `# quell: complete assertion`; auto-gitignored by `quell init`
- FLAGGED — edge cases with a one-line reason why they cannot be auto-tested

**5-gate pipeline** (formalized from the v1 verifier)
- Gate 1: AST validity + import check
- Gate 2: Originality (AST fingerprint + n-gram, no copy-paste)
- Gate 3: Security (no forbidden operations in generated test)
- Gate 4: Passes on correct code
- Gate 5: Fails on violated code

**Production Readiness Score (PRS)**
- 0–100 score across WRITTEN tests and their confidence values
- +5 modifier if all FLAGGED items carry `# quell: flagged`
- -10 modifier if any HIGH-confidence test is disabled with `@pytest.mark.skip`
- Tiers: GREEN ≥80 / YELLOW ≥60 / RED <60
- Posted as a PR comment by the GitHub Action; shown by `quell score`

**`quell score` rewrite**
- Reads PRS from `quell-report.json`; falls back to live scan
- `--badge` prints an SVG badge; `--json` for machine-readable output
- Shows WRITTEN/SCAFFOLDED/FLAGGED counts + average confidence

**`quell init` v2.0.0 defaults**
- Default LLM provider changed from `anthropic` to `groq` (`llama-3.3-70b-versatile`)
- New keys: `prs_threshold = 60`, `scaffold_dir = "tests/scaffold"`, `use_llm = false`
- Auto-adds scaffold dir to `.gitignore` on init

**Groq LLM provider**
- `quell auth set --provider groq --key sk-...` stores credentials in OS keyring
- Groq is the new default: faster and has a free tier
- `quell auth status --privacy` shows what gets sent per auth mode

**GitHub Action update**
- `quell install --action` writes updated workflow that posts a PRS comment on every PR
- PRS tier emoji (🟢/🟡/🔴) shown inline in the comment

---

## v1.0.0 — 2026-05-16 · Infrastructure-Aware Verified Testing

**QuellGraph** — persistent SQLite code-intelligence graph at `.quellgraph/graph.db`
- Incremental sha256-based AST builder — only changed files re-parsed
- BFS infra-tag propagation across call chains (3-hop verified in tests)
- CLI: `quell graph build / show / why / stale / stats`

**Ephemeral container engine**
- Auto-starts throwaway Docker containers for postgres, redis, localstack, mongo, smtp, rabbitmq, elasticsearch
- Hardcoded ephemeral credentials only — never reads `DATABASE_URL` or real creds
- Keep-alive lockfile — reuses running containers across short runs
- `quell teardown` stops all quelltest-managed containers
- pytest fixture injection into `conftest.py`

**6-factor confidence scorer**
- Factors: annotation coverage, constraint clarity, dependency clarity, graph coverage, docstring quality, mutation strength
- Tiers: HIGH ≥85 / MEDIUM ≥70 / LOW ≥50 / SKIP <50
- Write gate (default ≥50) and CI gate (default ≥70)

**New CLI flags on `quell check`**
- `--with-containers` — auto-start required infra containers
- `--min-confidence N` — override write threshold
- `--ci-confidence N` — override CI threshold
- `--keep-containers` — don't teardown after run
- `--graph-rebuild` — force graph rebuild before check

**Environment detection**
- 8 runtime types: LOCAL_DOCKER, GITHUB_ACTIONS, GITLAB_CI, CIRCLECI, DEVCONTAINER, DOCKER_IN_DOCKER, KUBERNETES_POD, NO_DOCKER
- Per-environment container strategy with CI setup hints

**Self-scan** — quelltest scanned itself: 58 requirements found, 12 verified tests written.

---

## v0.9.9.4 — 2026-05-14

- Engine accuracy: nested function scanning, syntax fixes, bare return violation injection, silent_fail stubs
- Skip functions where all required params are unknown types (no more guaranteed-failing stubs)
- CI matrix: Python 3.10–3.14, setup-uv v5

---

## v0.9.8 — 2026-05-12

- **GitHub Action** — composite action (`uses: shashank7109/quelltest_lib@main`); scans PRs, posts inline annotations, idempotent PR comment; `fail-on-gaps: true` blocks merges
- **GitHub App rewrite** — webhook server; no per-repo YAML; fetches changed files via Contents API
- `--format github` — outputs GitHub Actions annotation syntax
- `source_line` added to `Requirement` model

---

## v0.9.6.1 — 2026-05-12

- CUSTOM guard rules — `assert` statements now generate concrete stubs
- Concrete class preference — picks non-abstract implementors over base classes
- Assert violation injection — comments out assert line for Phase 2

---

## v0.9.5 — 2026-05-12

- `PYTHONPATH=src/` auto-set in pytest subprocess — fixes src-layout projects
- Builtin exception guard — `ValueError`, `TypeError`, etc. handled directly
- Skip abstract stubs — never instantiates ABC classes

---

## v0.9.4 — 2026-05-12

- Detects `try/except/raise` patterns and generates `must_raise` tests
- Detects standalone `raise` statements in guard branches

---

## v0.9.3 — 2026-05-12

- Auto-detects pytest when not in `sys.executable` environment (conda, venv, pipx)

---

## v0.9.2 — 2026-05-11

- Auto-loads `.env` family files into pytest subprocess — `.env`, `.env.example`, `.env.template`, `.env.local`, `.env.secrets`
- Surfaces real failure reason for rejected tests in `quell-report.json`

---

## v0.9.0 — 2026-05-11

- **Dual-engine architecture** — rule engine handles known patterns deterministically; framework engine handles FastAPI / Flask route guards
- Word-boundary check eliminates false stub injections on framework endpoints
- Root-cause Windows encoding bug fixed — `sys.executable` + UTF-8 subprocess

---

## v0.8.0 — 2026-05-11

- Full violation coverage — all `ConstraintKind` types get targeted injection
- Async function support — wraps test body in `asyncio.run()`

---

## v0.7.0 — 2026-05-11

- Fix duplicate kwargs in `not_null` stubs
- Fix `silent_fail` verification — correctly tests None-return paths

---

## v0.6.9 — 2026-05-10

- Pydantic classmethod stubs — correctly handles `@classmethod` validators
- Enum kwarg name fix
- Optional stub dedup — no more duplicate `Optional[X]` in generated code

---

## v0.6.1 — 2026-05-10

- Fix `asyncio.run()` crash in running event loop (Jupyter / IPython) — thread fallback
- `quell scan --fix` is now rule-engine-only by default — no LLM hang

---

## v0.6.0 — 2026-05-10

- **CodeGuardReader** — scans `if/raise`, `assert`, `try/except/raise` patterns from source; no docstrings needed
- `quell scan` command
- FixSuggester — interactive fix recommendations
- Always writes `quell-report.json` after every run

---

## v0.5.1 — 2026-05-09

- Fix auth login hang — `Connection: close` header, faster token error handling

---

## v0.5.0 — 2026-05-09

- **Auth system** — `quell auth login` with PKCE OAuth
- **PySpark reader** — `StructType` schemas (`nullable=False`, type checks)
- `quell pr` — posts scan results as GitHub PR comment
- `--no-llm` flag — disables all LLM calls

---

## v0.4.4 — 2026-05-08

- Rule engine improvements — boundary detection, stub generation
- `--version` / `-V` flag

---

## v0.4.0 — 2026-05-08

- **Spec-first architecture** — unified `Requirement` model; all readers return `list[Requirement]`
- Signature inspection — real parameter names and types in generated stubs
- Targeted violation injection per `ConstraintKind`
- Diagnostic report — `quell-report.json`

---

## v0.3.0 — 2026-05-07

- GitHub integration — PR comment poster, webhook listener
- VS Code extension scaffold
- First PyPI release

---

## v0.2.0 — 2026-05-07

- CI score tracking — `quell score --badge`
- Repair mode — auto-writes verified tests
- MCP server
- SDK — `from quell import Quell`

---

## v0.1.0 — 2026-05-07

- Initial release — Python 3.11+, Typer CLI, Pydantic v2, libcst
- Docstring reader — `Raises:` / `Returns:` blocks
- Pydantic reader — `Field` constraints and `Literal` types
- Two-phase verifier
- AST-safe writer — libcst injection, backup before write, restore on failure
