"""Create quell_spec6 issues in quelltest/quelltest_lib upstream."""
import json
import os
import urllib.request
import ssl

TOKEN = os.environ["GITHUB_TOKEN"]
REPO = "quelltest/quelltest_lib"
ASSIGNEE = "shashankbindal"
BASE = f"https://api.github.com/repos/{REPO}"
CTX = ssl.create_default_context()


def post(endpoint: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/{endpoint}",
        data=data,
        headers={
            "Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=CTX) as r:
        return json.load(r)


ISSUES = [
    {
        "title": "feat: add security model — ephemeral credential constants and forbidden-env guard",
        "labels": ["security", "enhancement"],
        "body": (
            "## What\n"
            "Add `EPHEMERAL_CREDS` hardcoded constants (postgres/redis/mongo/mysql/localstack) "
            "and a `FORBIDDEN_ENV_READS` guard that logs and ignores real production env vars at "
            "startup. Show a one-time trust message stored in `.quellgraph/trust_shown`.\n\n"
            "## Why\n"
            "quelltest must never touch real credentials. "
            "This is the non-negotiable security foundation for the container engine.\n\n"
            "## Files\n"
            "- `quell/infra/specs.py` (new) — `EPHEMERAL_CREDS`, `FORBIDDEN_ENV_READS`, `_assert_no_credential_reads()`\n"
            "- `quell/core/verifier.py` — call guard at startup\n\n"
            "## Acceptance Criteria\n"
            "- 13 forbidden env var names checked and logged (not raised) at startup\n"
            "- Trust message shown once; suppressed after `.quellgraph/trust_shown` exists\n"
            "- Unit test: guard logs but does not raise when a forbidden key is present"
        ),
        "slug": "security-model",
    },
    {
        "title": "feat: add environment detection layer (RuntimeEnvironment enum + strategy map)",
        "labels": ["infra", "enhancement"],
        "body": (
            "## What\n"
            "Add `quell/env/detector.py` with `RuntimeEnvironment` enum (8 types) and "
            "`detect_environment()` + `ENVIRONMENT_STRATEGY` map that maps each env to a "
            "container mode (testcontainers / dind / warn_skip / skip).\n\n"
            "## Why\n"
            "Each runtime needs a different container startup strategy. "
            "The engine must know where it is before starting any container.\n\n"
            "## Files\n"
            "- `quell/env/__init__.py` (new)\n"
            "- `quell/env/detector.py` (new)\n\n"
            "## Acceptance Criteria\n"
            "- All 8 environment types detected via env vars / filesystem signals\n"
            "- K8s + NO_DOCKER return warn_skip/skip with CI setup hints\n"
            "- Unit tests cover GITHUB_ACTIONS, LOCAL_DOCKER, KUBERNETES_POD, NO_DOCKER paths"
        ),
        "slug": "env-detection",
    },
    {
        "title": "feat: add QuellGraph SQLite schema and incremental AST builder",
        "labels": ["graph", "enhancement"],
        "body": (
            "## What\n"
            "Add `quell/graph/schema.sql` (full DDL: functions, classes, modules, calls, imports, "
            "inherits, uses_model, param_types tables) and `quell/graph/builder.py` "
            "(`QuellGraphBuilder`) with incremental sha256-based file invalidation, BFS infra-tag "
            "propagation, and cross-file call resolution.\n\n"
            "## Why\n"
            "A flat per-file scanner cannot detect transitive infra dependencies. "
            "QuellGraph sees the full call chain so the engine knows a function needs postgres "
            "even when sqlalchemy is 3 hops away.\n\n"
            "## Files\n"
            "- `quell/graph/__init__.py` (new)\n"
            "- `quell/graph/schema.sql` (new)\n"
            "- `quell/graph/builder.py` (new)\n\n"
            "## Acceptance Criteria\n"
            "- Cold build on 50-file project < 5 s; incremental (3 changed files) < 500 ms\n"
            "- `_propagate_infra_tags` BFS tested on synthetic 3-hop chain\n"
            "- Unit test: get_user -> db.query -> Session -> sqlalchemy returns {\"postgres\"}"
        ),
        "slug": "quellgraph-builder",
    },
    {
        "title": "feat: add QuellGraph query API (transitive tags, call chain, staleness)",
        "labels": ["graph", "enhancement"],
        "body": (
            "## What\n"
            "Add `quell/graph/query.py` with `QuellGraph` read API: `get_transitive_infra_tags`, "
            "`get_call_chain`, `get_pydantic_models_used`, `get_infra_dependency_path`, "
            "`find_stale_tests`, `has_cycles_in_chain`.\n\n"
            "## Why\n"
            "The confidence scorer and container engine both query the graph. "
            "They need a clean read-only API that does not touch the builder internals.\n\n"
            "## Files\n"
            "- `quell/graph/query.py` (new)\n\n"
            "## Acceptance Criteria\n"
            "- `get_infra_dependency_path` returns a human-readable shortest-path explanation\n"
            "- `find_stale_tests` correctly identifies functions touched by changed files\n"
            "- `has_cycles_in_chain` returns True for a synthetic cyclic call graph"
        ),
        "slug": "quellgraph-query",
    },
    {
        "title": "feat: add import dependency registry and container specs (IMPORT_SIGNALS + CONTAINER_SPECS)",
        "labels": ["infra", "enhancement"],
        "body": (
            "## What\n"
            "Add to `quell/infra/specs.py`: `IMPORT_SIGNALS` (import name -> infra tag), "
            "`INFRA_TYPE_NAMES` (parameter type names like Session -> postgres), "
            "`ContainerSpec` Pydantic model, and `CONTAINER_SPECS` registry for "
            "postgres, redis, localstack, mongo, smtp, rabbitmq, elasticsearch.\n\n"
            "## Why\n"
            "The graph builder uses IMPORT_SIGNALS to tag modules. "
            "The container engine uses CONTAINER_SPECS to know which image to start and "
            "how to wait for it to be ready.\n\n"
            "## Files\n"
            "- `quell/infra/__init__.py` (new)\n"
            "- `quell/infra/specs.py` (new)\n\n"
            "## Acceptance Criteria\n"
            "- All 7 container specs have image, port, wait_strategy, connection_url_template\n"
            "- `IMPORT_SIGNALS` covers sqlalchemy, redis, boto3, pymongo, pika, smtplib, elasticsearch\n"
            "- `ContainerSpec` validates correctly with Pydantic v2"
        ),
        "slug": "infra-specs",
    },
    {
        "title": "feat: add container engine with session management, lockfile reuse, and phase isolation",
        "labels": ["infra", "enhancement"],
        "body": (
            "## What\n"
            "Add `quell/infra/engine.py` (`ContainerEngine`, `ContainerSession`), "
            "`quell/infra/lockfile.py` (keep-alive container reuse via `.quellgraph/containers.lock`), "
            "`quell/infra/resolver.py` (DependencyProfile -> [ContainerSpec]), and "
            "`quell/infra/fixture_gen.py` (ContainerSpec -> pytest fixture source). "
            "Patch `quell/core/verifier.py` to inject `QUELL_TRANSACTION_ROLLBACK=true` "
            "so Phase 1 and Phase 2 always start from the same DB state.\n\n"
            "## Why\n"
            "Containers are started once per run (shared across all functions), reused across "
            "consecutive runs via the lockfile, and always destroyed on clean exit. "
            "Phase 2 mutation must not corrupt DB state left by Phase 1.\n\n"
            "## Files\n"
            "- `quell/infra/engine.py`, `quell/infra/lockfile.py`, `quell/infra/resolver.py`, `quell/infra/fixture_gen.py` (new)\n"
            "- `quell/core/verifier.py` (patch: transaction rollback env injection)\n\n"
            "## Acceptance Criteria\n"
            "- Orphaned containers from a previous killed run are detected and cleaned on next startup\n"
            "- `_start_or_reuse` reads lockfile before starting a new container\n"
            "- End-to-end: sample function with SQLAlchemy Session param reaches VERIFIED"
        ),
        "slug": "container-engine",
    },
    {
        "title": "feat: add six-factor confidence score system with tier gating",
        "labels": ["scoring", "enhancement"],
        "body": (
            "## What\n"
            "Add `quell/scoring/confidence.py` with `ConfidenceScore` and six scoring functions: "
            "`score_annotation_coverage` (25 pts), `score_constraint_clarity` (25 pts), "
            "`score_dependency_clarity` (20 pts), `score_graph_coverage` (15 pts), "
            "`score_docstring_quality` (10 pts), `score_mutation_strength` (5 pts). "
            "Add `TIERS` map (HIGH>=85, MEDIUM>=70, LOW>=50, SKIP<50) that gates writes and CI.\n\n"
            "## Why\n"
            "quelltest is the only test tool that scores its own certainty before writing. "
            "The tier system gates what enters CI (>=70) vs what is written at all (>=50).\n\n"
            "## Files\n"
            "- `quell/scoring/__init__.py` (new)\n"
            "- `quell/scoring/confidence.py` (new)\n"
            "- `quell/core/generator.py` (patch: apply confidence gate before writing)\n\n"
            "## Acceptance Criteria\n"
            "- Fully-typed pure function scores >= 80\n"
            "- Unannotated function with no docstring scores <= 40\n"
            "- Snapshot tests for known-high and known-low functions pass"
        ),
        "slug": "confidence-scorer",
    },
    {
        "title": "feat: extend CLI with quell graph commands, --with-containers flag, and quell teardown",
        "labels": ["dx", "enhancement"],
        "body": (
            "## What\n"
            "Extend `quell/cli.py` with: `quell graph build/show/why/stale/stats` subcommands, "
            "new `quell check` flags (`--with-containers`, `--min-confidence=N`, `--show-why`, "
            "`--keep-containers`, `--graph-rebuild`), and `quell teardown` command that stops "
            "and removes all quelltest-managed containers.\n\n"
            "## Why\n"
            "The graph and container engine need a user-facing surface. "
            "`quell graph why <function>` explains the dependency path so users understand "
            "why a container is being started.\n\n"
            "## Files\n"
            "- `quell/cli.py` (patch)\n\n"
            "## Acceptance Criteria\n"
            "- `quell graph build src/` runs QuellGraphBuilder and prints BuildReport\n"
            "- `quell graph stats` prints function/class/infra/pure counts\n"
            "- `quell teardown` reads lockfile and removes all tracked containers\n"
            "- `--min-confidence` flag is forwarded to the confidence gate in generator"
        ),
        "slug": "cli-extensions",
    },
]

numbers = []
for i, issue in enumerate(ISSUES, 1):
    payload = {
        "title": issue["title"],
        "body": issue["body"],
        "labels": issue["labels"],
        "assignees": [ASSIGNEE],
    }
    result = post("issues", payload)
    n = result["number"]
    numbers.append((n, issue["slug"], issue["title"]))
    print(f"  #{n}  {issue['title'][:70]}")

# Parent tracking issue
child_links = "\n".join(f"- #{n} — {title}" for n, _, title in numbers)
parent_body = (
    "## v1.0 — Infrastructure-Aware Verified Testing\n\n"
    "Tracks all spec6 work items. Closes when all child issues are merged.\n\n"
    "### Child issues\n"
    f"{child_links}\n\n"
    "### Systems\n"
    "1. **Ephemeral Container Engine** — zero-credential throwaway infra per test run\n"
    "2. **QuellGraph** — persistent local SQLite code-intelligence graph\n"
    "3. **Confidence Score System** — per-test certainty rating that gates writes\n\n"
    "### Rollout\n"
    "Week 1: QuellGraph foundation | Week 2: Confidence scorer | "
    "Week 3: Container engine | Week 4: Polish + dogfood"
)
parent = post("issues", {
    "title": "tracking: v1.0 — infrastructure-aware verified testing (spec6)",
    "body": parent_body,
    "labels": ["enhancement"],
    "assignees": [ASSIGNEE],
})
print(f"\nParent #{parent['number']}  {parent['title']}")
print("\nDone. All issues created in quelltest/quelltest_lib.")
