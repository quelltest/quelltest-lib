"""
Unit tests for quell.scoring.confidence — six-factor confidence scorer.

QuellGraph and FunctionInfo are constructed from minimal hand-built SQLite
databases so tests have no dependency on the builder.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from quell.graph.query import CallNode, ClassInfo, FunctionInfo
from quell.scoring.confidence import (
    CONSTRAINT_PTS,
    DEFAULT_CI_THRESHOLD,
    DEFAULT_WRITE_THRESHOLD,
    MUTATION_PTS,
    TIERS,
    ConfidenceScore,
    _field_has_constraint,
    _score_ast_guards,
    ci_filter,
    compute_confidence,
    filter_by_confidence,
    score_annotation_coverage,
    score_constraint_clarity,
    score_dependency_clarity,
    score_docstring_quality,
    score_graph_coverage,
    score_mutation_strength,
)

# ---------------------------------------------------------------------------
# Helpers to build minimal FunctionInfo objects
# ---------------------------------------------------------------------------


def _fn(
    *,
    annotation_coverage: float = 1.0,
    param_count: int = 2,
    has_docstring: bool = True,
    has_raises_block: bool = False,
    has_returns_block: bool = False,
    has_args_block: bool = False,
    purity_score: float = 1.0,
    infra_tags: list[str] | None = None,
    id: str = "fn-1",
) -> FunctionInfo:
    return FunctionInfo(
        id=id,
        name="test_func",
        file="test.py",
        line_start=1,
        docstring="Some doc." if has_docstring else None,
        is_pure=len(infra_tags or []) == 0,
        purity_score=purity_score,
        annotation_coverage=annotation_coverage,
        infra_tags=infra_tags or [],
        has_docstring=has_docstring,
        has_raises_block=has_raises_block,
        has_returns_block=has_returns_block,
        has_args_block=has_args_block,
        param_count=param_count,
    )


def _mock_graph(
    *,
    pydantic_models: list[ClassInfo] | None = None,
    infra_tags: set[str] | None = None,
    call_chain: list[CallNode] | None = None,
    has_cycles: bool = False,
) -> MagicMock:
    g = MagicMock()
    g.get_pydantic_models_used.return_value = pydantic_models or []
    g.get_transitive_infra_tags.return_value = infra_tags or set()
    g.get_call_chain.return_value = call_chain or []
    g.has_cycles_in_chain.return_value = has_cycles
    return g


def _call(is_resolved: bool) -> CallNode:
    return CallNode(
        function_id="fn-2" if is_resolved else "fn-unknown",
        name="helper",
        file="helper.py",
        is_resolved=is_resolved,
        infra_tags=[],
    )


# ---------------------------------------------------------------------------
# Factor 1: Annotation Coverage
# ---------------------------------------------------------------------------


class TestScoreAnnotationCoverage:
    def test_fully_typed_gives_25(self):
        fn = _fn(annotation_coverage=1.0)
        assert score_annotation_coverage(fn) == 25.0

    def test_half_typed_gives_12_5(self):
        fn = _fn(annotation_coverage=0.5)
        assert score_annotation_coverage(fn) == 12.5

    def test_untyped_gives_zero(self):
        fn = _fn(annotation_coverage=0.0)
        assert score_annotation_coverage(fn) == 0.0

    def test_returns_float(self):
        fn = _fn(annotation_coverage=0.8)
        assert isinstance(score_annotation_coverage(fn), float)


# ---------------------------------------------------------------------------
# Factor 2: Constraint Clarity
# ---------------------------------------------------------------------------


class TestFieldHasConstraint:
    def test_present_constraint(self):
        field = {"constraints": ["pydantic_field_gt_lt"]}
        assert _field_has_constraint(field, "pydantic_field_gt_lt") is True

    def test_absent_constraint(self):
        field = {"constraints": []}
        assert _field_has_constraint(field, "raises_block") is False

    def test_missing_constraints_key(self):
        assert _field_has_constraint({}, "raises_block") is False


class TestScoreAstGuards:
    def test_both_blocks(self):
        fn = _fn(has_raises_block=True, has_returns_block=True)
        pts = _score_ast_guards(fn)
        assert pts == CONSTRAINT_PTS["raises_block"] + CONSTRAINT_PTS["returns_block"]

    def test_no_blocks(self):
        fn = _fn(has_raises_block=False, has_returns_block=False)
        assert _score_ast_guards(fn) == 0


class TestScoreConstraintClarity:
    def test_no_models_no_guards_gives_zero(self):
        fn = _fn(has_raises_block=False, has_returns_block=False)
        g = _mock_graph(pydantic_models=[])
        assert score_constraint_clarity(fn, g) == 0.0

    def test_capped_at_25(self):
        # Create a field with many constraints to overflow
        field = {"constraints": list(CONSTRAINT_PTS.keys())}
        cls = ClassInfo(id="c1", name="M", file="m.py", is_pydantic=True, fields=[field])
        fn = _fn(has_raises_block=True, has_returns_block=True)
        g = _mock_graph(pydantic_models=[cls])
        score = score_constraint_clarity(fn, g)
        assert score == 25.0

    def test_raises_block_contributes(self):
        fn = _fn(has_raises_block=True, has_returns_block=False)
        g = _mock_graph(pydantic_models=[])
        score = score_constraint_clarity(fn, g)
        assert score == float(CONSTRAINT_PTS["raises_block"])

    def test_pydantic_field_constraint_contributes(self):
        field = {"constraints": ["pydantic_field_gt_lt"]}
        cls = ClassInfo(id="c1", name="M", file="m.py", is_pydantic=True, fields=[field])
        fn = _fn(has_raises_block=False, has_returns_block=False)
        g = _mock_graph(pydantic_models=[cls])
        score = score_constraint_clarity(fn, g)
        assert score == float(CONSTRAINT_PTS["pydantic_field_gt_lt"])


# ---------------------------------------------------------------------------
# Factor 3: Dependency Clarity
# ---------------------------------------------------------------------------


class TestScoreDependencyClarity:
    def test_pure_function_gets_20(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn(infra_tags=[])
        g = _mock_graph(infra_tags=set())
        score = score_dependency_clarity(fn, g, RuntimeEnvironment.LOCAL_DOCKER)
        assert score == 20.0

    def test_no_docker_env_gets_zero(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn(infra_tags=["postgres"])
        g = _mock_graph(infra_tags={"postgres"})
        score = score_dependency_clarity(fn, g, RuntimeEnvironment.NO_DOCKER)
        assert score == 0.0

    def test_known_deps_docker_env_gives_18(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn(infra_tags=["postgres"])
        g = _mock_graph(infra_tags={"postgres"})
        score = score_dependency_clarity(fn, g, RuntimeEnvironment.LOCAL_DOCKER)
        assert score == 18.0

    def test_partial_unmapped_deps_partial_score(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn(infra_tags=["postgres", "unknown_db"])
        g = _mock_graph(infra_tags={"postgres", "unknown_db"})
        score = score_dependency_clarity(fn, g, RuntimeEnvironment.LOCAL_DOCKER)
        # 1 mapped / 2 total = 0.5 * 12 = 6.0
        assert score == 6.0


# ---------------------------------------------------------------------------
# Factor 4: Graph Coverage
# ---------------------------------------------------------------------------


class TestScoreGraphCoverage:
    def test_no_call_chain_gives_8(self):
        fn = _fn()
        g = _mock_graph(call_chain=[])
        assert score_graph_coverage(fn, g) == 8.0

    def test_fully_resolved_no_cycles_gives_15(self):
        fn = _fn()
        g = _mock_graph(call_chain=[_call(True), _call(True)], has_cycles=False)
        score = score_graph_coverage(fn, g)
        assert score == 15.0

    def test_cycle_penalty_applied(self):
        fn = _fn()
        g = _mock_graph(call_chain=[_call(True), _call(True)], has_cycles=True)
        no_cycle_graph = _mock_graph(call_chain=[_call(True), _call(True)], has_cycles=False)
        score_no_cycle = score_graph_coverage(_fn(), no_cycle_graph)
        score_with_cycle = score_graph_coverage(fn, g)
        assert score_with_cycle == score_no_cycle - 3

    def test_partially_resolved_scores_proportionally(self):
        fn = _fn()
        g = _mock_graph(call_chain=[_call(True), _call(False)], has_cycles=False)
        score = score_graph_coverage(fn, g)
        # resolve_ratio = 0.5, base = 0.5*12=6, no cycle penalty so +3 → 9
        assert score == 9.0

    def test_capped_at_15(self):
        fn = _fn()
        many_resolved = [_call(True)] * 10
        g = _mock_graph(call_chain=many_resolved, has_cycles=False)
        assert score_graph_coverage(fn, g) <= 15.0


# ---------------------------------------------------------------------------
# Factor 5: Docstring Quality
# ---------------------------------------------------------------------------


class TestScoreDocstringQuality:
    def test_no_docstring_gives_zero(self):
        fn = _fn(has_docstring=False)
        assert score_docstring_quality(fn) == 0.0

    def test_bare_docstring_gives_2(self):
        fn = _fn(has_docstring=True, has_raises_block=False, has_returns_block=False, has_args_block=False)
        assert score_docstring_quality(fn) == 2.0

    def test_all_blocks_gives_10(self):
        fn = _fn(has_docstring=True, has_raises_block=True, has_returns_block=True, has_args_block=True)
        assert score_docstring_quality(fn) == 10.0

    def test_raises_block_only_gives_6(self):
        fn = _fn(has_docstring=True, has_raises_block=True, has_returns_block=False, has_args_block=False)
        assert score_docstring_quality(fn) == 6.0


# ---------------------------------------------------------------------------
# Factor 6: Mutation Strength
# ---------------------------------------------------------------------------


class TestScoreMutationStrength:
    def test_boundary_gives_5(self):
        assert score_mutation_strength("boundary") == 5.0

    def test_unknown_type_gives_1(self):
        assert score_mutation_strength("something_exotic") == 1.0

    def test_all_known_types_have_entries(self):
        for req_type in MUTATION_PTS:
            score = score_mutation_strength(req_type)
            assert 1 <= score <= 5


# ---------------------------------------------------------------------------
# ConfidenceScore dataclass
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    def _high_score(self) -> ConfidenceScore:
        return ConfidenceScore(
            annotation_coverage=25.0,
            constraint_clarity=25.0,
            dependency_clarity=20.0,
            graph_coverage=15.0,
            docstring_quality=10.0,
            mutation_strength=5.0,
        )

    def _skip_score(self) -> ConfidenceScore:
        return ConfidenceScore(
            annotation_coverage=0.0,
            constraint_clarity=0.0,
            dependency_clarity=0.0,
            graph_coverage=8.0,
            docstring_quality=0.0,
            mutation_strength=1.0,
        )

    def test_total_sums_factors(self):
        s = self._high_score()
        assert s.total == 100

    def test_tier_high(self):
        s = self._high_score()
        assert s.label == "HIGH"
        assert s.write_allowed is True
        assert s.run_in_ci is True

    def test_tier_skip(self):
        s = self._skip_score()
        assert s.label == "SKIP"
        assert s.write_allowed is False

    def test_passes_threshold_default(self):
        s = self._high_score()
        assert s.passes_threshold() is True

    def test_fails_threshold(self):
        s = self._skip_score()
        assert s.passes_threshold() is False

    def test_custom_threshold(self):
        # 12.5 + 12.5 + 10.0 + 8.0 + 2.0 + 1.0 = 46
        s = ConfidenceScore(
            annotation_coverage=12.5,
            constraint_clarity=12.5,
            dependency_clarity=10.0,
            graph_coverage=8.0,
            docstring_quality=2.0,
            mutation_strength=1.0,
        )
        assert s.total == 46
        assert s.passes_threshold(min_confidence=45) is True
        assert s.passes_threshold(min_confidence=50) is False

    def test_str_representation(self):
        s = self._high_score()
        text = str(s)
        assert "100" in text
        assert "HIGH" in text


# ---------------------------------------------------------------------------
# TIERS structure
# ---------------------------------------------------------------------------


class TestTiers:
    def test_four_tiers(self):
        assert len(TIERS) == 4

    def test_covers_full_range(self):
        assert TIERS[-1][0] == 0
        assert TIERS[0][1] == 100

    def test_thresholds(self):
        assert DEFAULT_WRITE_THRESHOLD == 50
        assert DEFAULT_CI_THRESHOLD == 70


# ---------------------------------------------------------------------------
# compute_confidence (integration)
# ---------------------------------------------------------------------------


class TestComputeConfidence:
    def test_pure_well_documented_function(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn(
            annotation_coverage=1.0,
            has_docstring=True,
            has_raises_block=True,
            has_returns_block=True,
            has_args_block=True,
            infra_tags=[],
        )
        g = _mock_graph(
            pydantic_models=[],
            infra_tags=set(),
            call_chain=[_call(True), _call(True)],
            has_cycles=False,
        )
        score = compute_confidence(fn, g, RuntimeEnvironment.LOCAL_DOCKER, "boundary")
        assert score.total >= 70  # should be at least MEDIUM

    def test_returns_confidence_score_instance(self):
        from quell.env.detector import RuntimeEnvironment
        fn = _fn()
        g = _mock_graph()
        result = compute_confidence(fn, g, RuntimeEnvironment.LOCAL_DOCKER, "boundary")
        assert isinstance(result, ConfidenceScore)


# ---------------------------------------------------------------------------
# Confidence gate helper functions
# ---------------------------------------------------------------------------


class TestConfidenceGate:
    def _make_test(self, score: int | None):
        from quell.core.models import GeneratedTest
        return GeneratedTest(
            requirement_id="req-1",
            test_function_name="test_foo",
            test_code="def test_foo(): pass",
            test_file_path=Path("tests/test_foo.py"),
            explanation="test",
            generated_by="rule_engine",
            confidence_score=score,
        )

    def test_filter_passes_high_scores(self):
        tests = [self._make_test(85), self._make_test(70)]
        accepted, skipped = filter_by_confidence(tests, min_confidence=50)
        assert len(accepted) == 2
        assert len(skipped) == 0

    def test_filter_skips_low_scores(self):
        tests = [self._make_test(30), self._make_test(45)]
        accepted, skipped = filter_by_confidence(tests, min_confidence=50)
        assert len(accepted) == 0
        assert len(skipped) == 2

    def test_none_score_always_passes(self):
        tests = [self._make_test(None)]
        accepted, skipped = filter_by_confidence(tests, min_confidence=50)
        assert len(accepted) == 1

    def test_ci_filter(self):
        tests = [self._make_test(85), self._make_test(60)]
        ci_tests, review = ci_filter(tests, ci_confidence=70)
        assert len(ci_tests) == 1
        assert len(review) == 1

    def test_meets_confidence_method(self):
        t = self._make_test(49)
        assert t.meets_confidence(50) is False
        t2 = self._make_test(50)
        assert t2.meets_confidence(50) is True
