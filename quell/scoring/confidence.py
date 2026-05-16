"""
Six-factor confidence scorer for generated tests.

Every generated test receives a score from 0–100 before anything is written
to disk. The score gates writes (≥50), CI enforcement (≥70), and appears
in PR annotations and CLI output.

Factor groups and maximum points:
  1. Annotation Coverage    25 pts — are params and return type typed?
  2. Constraint Clarity     25 pts — how many checkable rules exist?
  3. Dependency Clarity     20 pts — can we actually run this function?
  4. Graph Coverage         15 pts — does the graph understand its call chain?
  5. Docstring Quality      10 pts — does documentation describe behaviour?
  6. Mutation Strength       5 pts — how precisely can we inject the violation?
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quell.env.detector import RuntimeEnvironment
    from quell.graph.query import FunctionInfo, QuellGraph

# ---------------------------------------------------------------------------
# Factor 2: constraint type weights
# ---------------------------------------------------------------------------

CONSTRAINT_PTS: dict[str, int] = {
    "pydantic_field_gt_lt": 8,
    "pydantic_field_ge_le": 7,
    "literal_type": 6,
    "raises_block": 5,
    "if_raise_guard": 4,
    "not_null_annotation": 3,
    "returns_block": 2,
    "pydantic_validator": 2,
}

# ---------------------------------------------------------------------------
# Factor 6: mutation strength weights
# ---------------------------------------------------------------------------

MUTATION_PTS: dict[str, int] = {
    "boundary": 5,
    "enum_valid": 4,
    "must_raise": 4,
    "not_null": 3,
    "type_check": 3,
    "returns": 2,
}

# ---------------------------------------------------------------------------
# Confidence tiers
# (min, max, label, stars, write_allowed, run_in_ci)
# ---------------------------------------------------------------------------

TIERS: list[tuple[int, int, str, str, bool, bool]] = [
    (85, 100, "HIGH",   "★★★★★", True,  True),
    (70,  84, "MEDIUM", "★★★★☆", True,  True),
    (50,  69, "LOW",    "★★★☆☆", True,  False),
    (0,   49, "SKIP",   "★☆☆☆☆", False, False),
]

DEFAULT_WRITE_THRESHOLD = 50
DEFAULT_CI_THRESHOLD = 70

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ConfidenceScore:
    """Full breakdown of a confidence score for one generated test."""

    annotation_coverage: float
    constraint_clarity: float
    dependency_clarity: float
    graph_coverage: float
    docstring_quality: float
    mutation_strength: float

    @property
    def total(self) -> int:
        return round(
            self.annotation_coverage
            + self.constraint_clarity
            + self.dependency_clarity
            + self.graph_coverage
            + self.docstring_quality
            + self.mutation_strength
        )

    @property
    def tier(self) -> tuple[int, int, str, str, bool, bool]:
        for entry in TIERS:
            if entry[0] <= self.total <= entry[1]:
                return entry
        return TIERS[-1]

    @property
    def label(self) -> str:
        return self.tier[2]

    @property
    def stars(self) -> str:
        return self.tier[3]

    @property
    def write_allowed(self) -> bool:
        return self.tier[4]

    @property
    def run_in_ci(self) -> bool:
        return self.tier[5]

    def passes_threshold(self, min_confidence: int = DEFAULT_WRITE_THRESHOLD) -> bool:
        return self.total >= min_confidence

    def __str__(self) -> str:
        return f"{self.total}/100  {self.stars}  {self.label}"


# ---------------------------------------------------------------------------
# Factor 1: Annotation Coverage (max 25 pts)
# ---------------------------------------------------------------------------


def score_annotation_coverage(fn: FunctionInfo) -> float:
    """
    Score based on precomputed annotation_coverage ratio from QuellGraph.

    annotation_coverage = typed_slots / total_slots where total_slots
    = param_count + 1 (for return type). Functions with no slots get 0.
    """
    return round(fn.annotation_coverage * 25, 2)


# ---------------------------------------------------------------------------
# Factor 2: Constraint Clarity (max 25 pts)
# ---------------------------------------------------------------------------


def _field_has_constraint(field: dict, kind: str) -> bool:
    """Check if a Pydantic model field dict signals a given constraint kind."""
    constraints = field.get("constraints", [])
    return kind in constraints


def _score_ast_guards(fn: FunctionInfo) -> int:
    """Award points for documented guard clauses visible in FunctionInfo."""
    pts = 0
    if fn.has_raises_block:
        pts += CONSTRAINT_PTS["raises_block"]
    if fn.has_returns_block:
        pts += CONSTRAINT_PTS["returns_block"]
    return pts


def score_constraint_clarity(fn: FunctionInfo, graph: QuellGraph) -> float:
    """
    Score based on how many verifiable constraints the function expresses.

    Checks Pydantic model field constraints (if field metadata is stored)
    and docstring guard blocks (raises/returns).
    """
    score = 0
    for model in graph.get_pydantic_models_used(fn.id):
        for field in model.fields:
            for kind, pts in CONSTRAINT_PTS.items():
                if _field_has_constraint(field, kind):
                    score += pts
    score += _score_ast_guards(fn)
    return min(float(score), 25.0)


# ---------------------------------------------------------------------------
# Factor 3: Dependency Clarity (max 20 pts)
# ---------------------------------------------------------------------------


def score_dependency_clarity(
    fn: FunctionInfo,
    graph: QuellGraph,
    env: RuntimeEnvironment,
) -> float:
    """
    Score based on whether we can actually execute this function during testing.

    Pure functions (no infra tags) get full marks. Functions needing containers
    score based on whether the current environment supports Docker.
    """
    from quell.env.detector import ENVIRONMENT_STRATEGY
    from quell.infra.specs import CONTAINER_SPECS

    tags = graph.get_transitive_infra_tags(fn.id)

    if not tags:
        return 20.0

    strategy = ENVIRONMENT_STRATEGY[env]
    if strategy.mode in ("warn_skip", "skip"):
        return 0.0

    unmapped = tags - set(CONTAINER_SPECS.keys())
    if unmapped:
        mapped_count = len(tags) - len(unmapped)
        if len(tags) == 0:
            return 0.0
        mapped_ratio = mapped_count / len(tags)
        return round(mapped_ratio * 12, 2)

    return 18.0


# ---------------------------------------------------------------------------
# Factor 4: Graph Coverage (max 15 pts)
# ---------------------------------------------------------------------------


def score_graph_coverage(fn: FunctionInfo, graph: QuellGraph) -> float:
    """
    Score based on how well the QuellGraph understands the call chain.

    No outgoing calls → 8 pts (simple function). Fully resolved call chain
    → up to 15 pts. Cycles reduce the score by 3 pts.
    """
    chain = graph.get_call_chain(fn.id, depth=5)
    if not chain:
        return 8.0

    resolved = sum(1 for c in chain if c.is_resolved)
    resolve_ratio = resolved / len(chain)
    base = round(resolve_ratio * 12, 2)
    cycle_penalty = 3 if graph.has_cycles_in_chain(fn.id) else 0
    return min(base + (3 - cycle_penalty), 15.0)


# ---------------------------------------------------------------------------
# Factor 5: Docstring Quality (max 10 pts)
# ---------------------------------------------------------------------------


def score_docstring_quality(fn: FunctionInfo) -> float:
    """Score based on how thoroughly the function is documented."""
    if not fn.has_docstring:
        return 0.0
    score = 2
    if fn.has_raises_block:
        score += 4
    if fn.has_returns_block:
        score += 2
    if fn.has_args_block:
        score += 2
    return float(score)


# ---------------------------------------------------------------------------
# Factor 6: Mutation Strength (max 5 pts)
# ---------------------------------------------------------------------------


def score_mutation_strength(requirement_type: str) -> float:
    """Score based on how precisely we can inject a violation for this requirement."""
    return float(MUTATION_PTS.get(requirement_type, 1))


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------


def compute_confidence(
    fn: FunctionInfo,
    graph: QuellGraph,
    env: RuntimeEnvironment,
    requirement_type: str,
) -> ConfidenceScore:
    """
    Compute the full six-factor ConfidenceScore for a function/requirement pair.
    """
    return ConfidenceScore(
        annotation_coverage=score_annotation_coverage(fn),
        constraint_clarity=score_constraint_clarity(fn, graph),
        dependency_clarity=score_dependency_clarity(fn, graph, env),
        graph_coverage=score_graph_coverage(fn, graph),
        docstring_quality=score_docstring_quality(fn),
        mutation_strength=score_mutation_strength(requirement_type),
    )


# ---------------------------------------------------------------------------
# Confidence gate helpers (operate on GeneratedTest without importing generator)
# ---------------------------------------------------------------------------


def filter_by_confidence(
    tests: list,
    min_confidence: int = DEFAULT_WRITE_THRESHOLD,
) -> tuple[list, list]:
    """
    Partition GeneratedTest objects into (accepted, skipped) by write threshold.

    Tests without a score (confidence_score=None) always pass through.
    Returns (accepted, skipped) so callers can log what was gated.
    """
    accepted = []
    skipped = []
    for test in tests:
        if test.meets_confidence(min_confidence):
            accepted.append(test)
        else:
            skipped.append(test)
    return accepted, skipped


def ci_filter(
    tests: list,
    ci_confidence: int = DEFAULT_CI_THRESHOLD,
) -> tuple[list, list]:
    """Partition GeneratedTest objects into (ci_enforced, review_only) by CI threshold."""
    ci_enforced = []
    review_only = []
    for test in tests:
        if test.meets_confidence(ci_confidence):
            ci_enforced.append(test)
        else:
            review_only.append(test)
    return ci_enforced, review_only
