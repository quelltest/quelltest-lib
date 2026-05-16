"""
Generates candidate killing tests for survived mutants.

Strategy:
1. For known operators (BOUNDARY_SHIFT, ARITHMETIC_SWAP, etc.): use rule-based generation.
   These are deterministic and fast. No LLM needed.
2. For UNKNOWN or complex operators: use LLM with rich context.
3. Always return a GeneratedTest with test_code as a valid Python function string.

Confidence gate:
  After scoring, call quell.scoring.confidence.filter_by_confidence() to drop
  tests below the threshold before verification and writing. Default thresholds:
    write  threshold: 50  (override: --min-confidence=N)
    CI     threshold: 70  (override: quell.toml ci_confidence)
"""
from __future__ import annotations

import re
from pathlib import Path

from quell.core.models import (
    GeneratedTest,
    MutationOperator,
    QuellConfig,
    SurvivedMutant,
)
from quell.llm.client import LLMClient


class TestGenerator:
    """
    Generates a test function for a given SurvivedMutant.

    Usage:
        generator = TestGenerator(llm_client, config)
        test = await generator.generate(mutant)
    """

    def __init__(self, llm_client: LLMClient, config: QuellConfig):
        self.llm = llm_client
        self.config = config

    @staticmethod
    def _test_file(mutant: SurvivedMutant) -> Path:
        return mutant.test_file_path or (
            mutant.file_path.parent / "tests" / f"test_{mutant.file_path.stem}.py"
        )

    async def generate(self, mutant: SurvivedMutant) -> GeneratedTest:
        """Main entry point. Routes to rule-based or LLM generator."""
        if mutant.operator == MutationOperator.BOUNDARY_SHIFT:
            return self._generate_boundary_test(mutant)
        elif mutant.operator == MutationOperator.ARITHMETIC_SWAP:
            return self._generate_arithmetic_test(mutant)
        elif mutant.operator == MutationOperator.COMPARISON_FLIP:
            return self._generate_comparison_test(mutant)
        elif mutant.operator == MutationOperator.CONSTANT_MUTATION:
            return self._generate_constant_test(mutant)
        elif mutant.operator == MutationOperator.RETURN_MUTATION:
            return self._generate_return_test(mutant)
        elif mutant.operator == MutationOperator.LOGICAL_SWAP:
            return self._generate_logical_test(mutant)
        else:
            # Fall through to LLM for UNKNOWN, STATEMENT_REMOVAL, STRING_MUTATION, etc.
            return await self._generate_llm_test(mutant)

    def _make_test_name(self, mutant: SurvivedMutant) -> str:
        func = mutant.function_name or "code"
        return f"test_quell_{func}_mutant_{mutant.id}"

    def _generate_boundary_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        """
        For boundary shifts (> → >=), we need a test at the exact boundary value.

        Strategy: extract the RHS value from the condition.
        Example: "if amount > 0" mutated to "if amount >= 0"
        → Test: call function with amount=0, expect the ORIGINAL behavior (reject/different outcome)
        """
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)

        # Extract boundary value from original code using regex
        boundary_match = re.search(r'[><=!]+\s*(\d+)', mutant.original_code)
        boundary_val = boundary_match.group(1) if boundary_match else "0"

        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    This is a boundary condition test. The mutation shifts the boundary,
    so we test the exact boundary value to ensure correct behavior.
    """
    # The mutation changed a boundary condition.
    # Test with the exact boundary value ({boundary_val}) to expose the difference.
    # TODO: Replace with actual call to {func} with a boundary input.
    # Example: assert {func}({boundary_val}) == <expected_original_behavior>
    raise NotImplementedError(
        "Complete this test: call {func} with boundary value {boundary_val} "
        "and assert the ORIGINAL behavior (not the mutant behavior)."
    )
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation=(
                f"Boundary test at value {boundary_val} exposes the "
                f"{mutant.original_code.strip()} vs {mutant.mutated_code.strip()} difference"
            ),
            operator=mutant.operator,
            generated_by="rule_based",
        )

    def _generate_arithmetic_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        """
        For arithmetic swaps (+ → -), we need distinct non-zero inputs.

        Strategy: use inputs where a+b != a-b, i.e., b != 0.
        Example: "result = x + y" mutated to "result = x - y"
        → Test: x=3, y=2 → original gives 5, mutant gives 1
        """
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)

        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    Arithmetic mutation test. We need non-zero, non-equal inputs
    so that the original operator and mutant operator give different results.
    """
    # TODO: Replace with actual call to {func} with specific numeric inputs
    # Use inputs where the ORIGINAL and MUTANT operators give different results.
    # For + vs -: use (3, 2) → original=5, mutant=1
    # For * vs /: use (6, 3) → original=18, mutant=2
    raise NotImplementedError(
        "Complete this test: call {func} with numeric inputs that "
        "produce different results under + vs - (or the relevant operators)."
    )
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation="Arithmetic test with non-zero inputs exposes operator difference",
            operator=mutant.operator,
            generated_by="rule_based",
        )

    def _generate_comparison_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)
        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    Comparison flip test. We need an input where the comparison is TRUE
    in the original but FALSE in the mutant (or vice versa).
    """
    # TODO: Call {func} with input that makes original comparison TRUE
    # and assert behavior that would differ if comparison were flipped.
    raise NotImplementedError("Complete this test for comparison flip mutation.")
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation="Comparison flip test with value that makes one branch true and other false",
            operator=mutant.operator,
            generated_by="rule_based",
        )

    def _generate_constant_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)
        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    Constant mutation test. The mutant changed a literal constant value.
    We need to assert the exact expected value to catch this change.
    """
    # TODO: Call {func} and assert the EXACT expected output.
    # Avoid "assert result > 0" — use "assert result == <exact_value>"
    raise NotImplementedError("Complete this test with an exact value assertion.")
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation="Exact value assertion catches constant mutation",
            operator=mutant.operator,
            generated_by="rule_based",
        )

    def _generate_return_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)
        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    Return value mutation test. The mutant changed what is returned.
    We must assert the EXACT return value, not just that it's truthy.
    """
    # TODO: Call {func} and assert it does NOT return None.
    # result = {func}(...)
    # assert result is not None
    # assert result == <exact_expected_value>
    raise NotImplementedError("Complete this test: assert exact return value, not just truthiness.")
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation="Return value assertion (not None, exact value) kills return mutation",
            operator=mutant.operator,
            generated_by="rule_based",
        )

    def _generate_logical_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        func = mutant.function_name or "function_under_test"
        test_name = self._make_test_name(mutant)
        test_code = f'''def {test_name}():
    """
    Kills mutant {mutant.id}: {mutant.original_code.strip()} → {mutant.mutated_code.strip()}

    Logical operator mutation test. The mutant changed 'and' to 'or' or similar.
    We need a test where ONE condition is true and the OTHER is false.
    With 'and': result is False. With 'or': result is True.
    """
    # TODO: Call {func} with inputs where EXACTLY ONE condition is true.
    # This exposes the difference between 'and' and 'or'.
    raise NotImplementedError("Complete this test: use inputs where only one condition holds.")
'''
        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=test_name,
            test_code=test_code,
            test_file_path=self._test_file(mutant),
            explanation="Single-condition-true input exposes and/or operator difference",
            operator=mutant.operator,
            generated_by="rule_based",
        )

    async def _generate_llm_test(self, mutant: SurvivedMutant) -> GeneratedTest:
        """Use LLM for complex or UNKNOWN mutations."""
        from quell.llm.prompts import build_test_generation_prompt

        prompt = build_test_generation_prompt(mutant)
        response = await self.llm.generate(prompt)

        # Extract Python code block from response
        code = self._extract_code_block(response)
        func_name = self._extract_function_name(code) or self._make_test_name(mutant)

        return GeneratedTest(
            mutant_id=mutant.id,
            test_function_name=func_name,
            test_code=code,
            test_file_path=self._test_file(mutant),
            explanation=f"LLM-generated test for {mutant.operator.value} mutation",
            operator=mutant.operator,
            generated_by=f"llm:{self.config.llm_model}",
        )

    def _extract_code_block(self, response: str) -> str:
        """Extract ```python ... ``` block from LLM response."""
        match = re.search(r'```python\n(.*?)```', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()

    def _extract_function_name(self, code: str) -> str | None:
        """Extract the function name from generated code."""
        match = re.search(r'^def\s+(test_\w+)', code, re.MULTILINE)
        return match.group(1) if match else None
