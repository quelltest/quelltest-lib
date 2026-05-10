"""
Rule-based test generation. Fast, deterministic, no LLM required.

Pipeline per requirement:
  1. Inspect function signature via AST (sig_inspector)
  2. Build valid call stubs from type annotations / param names
  3. Generate a real callable test (not a TODO scaffold)
  4. Track unknown types for the diagnostic report

ConstraintKind → test strategy:
  MUST_RAISE   → pytest.raises(ExcType): func(violating_args)
  BOUNDARY     → assert func(boundary_val) raises or returns sentinel
  ENUM_VALID   → pytest.raises: func(invalid_enum_value)
  MUST_RETURN  → assert func(valid_args) is not None (+ type check)
  BUG_REPRO    → skeleton test that currently fails
"""
from __future__ import annotations

import re
from pathlib import Path

from quell.core.models import ConstraintKind, GeneratedTest, Requirement
from quell.synthesis import sig_inspector


class RuleEngine:
    """Deterministic rule-based test generator. No LLM required."""

    def can_handle(self, req: Requirement) -> bool:
        return req.constraint_kind in {
            ConstraintKind.MUST_RAISE,
            ConstraintKind.BOUNDARY,
            ConstraintKind.ENUM_VALID,
            ConstraintKind.MUST_RETURN,
            ConstraintKind.BUG_REPRO,
            # code_guard kinds
            ConstraintKind.NOT_NULL,
            ConstraintKind.TYPE_CHECK,
            ConstraintKind.SILENT_FAIL,
        }

    def generate(self, req: Requirement) -> GeneratedTest | None:
        if req.constraint_kind == ConstraintKind.MUST_RAISE:
            return self._must_raise(req)
        if req.constraint_kind == ConstraintKind.BOUNDARY:
            return self._boundary(req)
        if req.constraint_kind == ConstraintKind.ENUM_VALID:
            return self._enum(req)
        if req.constraint_kind == ConstraintKind.MUST_RETURN:
            return self._must_return(req)
        if req.constraint_kind == ConstraintKind.BUG_REPRO:
            return self._bug_repro(req)
        if req.constraint_kind == ConstraintKind.NOT_NULL:
            return self._not_null(req)
        if req.constraint_kind == ConstraintKind.TYPE_CHECK:
            return self._type_check(req)
        if req.constraint_kind == ConstraintKind.SILENT_FAIL:
            return self._silent_fail(req)
        return None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _test_file(self, req: Requirement) -> Path:
        return (
            req.target_file.parent.parent / "tests" /
            f"test_{req.target_file.stem}.py"
        )

    def _name(self, req: Requirement) -> str:
        func = re.sub(r"[^a-z0-9_]", "_", req.target_function.lower())
        kind = req.constraint_kind.value
        return f"test_quell_{func}_{kind}_{req.id[:8]}"

    def _sig_info(self, req: Requirement) -> tuple[str, str, list[str], list[str]]:
        """Return (call_expr, fixture_params_str, fixtures, unknown_types).

        call_expr is the full call: 'func(arg1=val1, arg2=val2)'
        For class methods: 'ClassName().method(args)' or 'obj.method(args)'
        """
        sig = sig_inspector.inspect(req.target_function, req.target_file)
        sig_inspector.module_path(req.target_file)
        func = req.target_function
        unknown: list[str] = []
        fixtures: list[str] = []

        if sig is None:
            # No signature found — generate a minimal stub
            call = f"{func}()"
            return call, "", fixtures, [f"sig_not_found:{func}"]

        call_args, fixtures, unknown = sig_inspector.stub_for_call(sig)

        if sig.is_method and sig.class_name:
            # Inspect __init__ to build instantiation
            init_sig = sig_inspector.inspect_init(sig.class_name, req.target_file)
            if init_sig is not None and init_sig.required_params:
                init_args, init_fix, init_unk = sig_inspector.stub_for_call(init_sig)
                fixtures.extend(init_fix)
                unknown.extend(init_unk)
                inst = f"{sig.class_name}({init_args})"
            else:
                inst = f"{sig.class_name}()"
            call = f"{inst}.{func}({call_args})"
        else:
            call = f"{func}({call_args})"

        fixture_str = f"({', '.join(dict.fromkeys(fixtures))})" if fixtures else "()"
        return call, fixture_str, list(dict.fromkeys(fixtures)), unknown

    def _import_line(self, req: Requirement) -> str:
        mod = sig_inspector.module_path(req.target_file)
        sig = sig_inspector.inspect(req.target_function, req.target_file)
        if sig and sig.is_method and sig.class_name:
            return f"from {mod} import {sig.class_name}"
        return f"from {mod} import {req.target_function}"

    def _setup_lines(self, fixtures: list[str]) -> str:
        if "tmp_path" in fixtures:
            return '    (tmp_path / "test_file.py").write_text("def foo(): pass\\n")\n'
        return ""

    # ── generators ───────────────────────────────────────────────────────────

    def _must_raise(self, req: Requirement) -> GeneratedTest:
        exc = "Exception"
        search_text = req.description + " " + (req.expected_behavior or "")
        m = re.search(r"\braises?\s+(\w+Error|\w+Exception)", search_text, re.I)
        if m:
            exc = m.group(1)

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        # Intentionally skip _setup_lines — we want Path stubs to point to
        # non-existent files so the function actually raises (FileNotFoundError etc.)
        setup = ""
        name = self._name(req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    with pytest.raises({exc}):
        {call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"pytest.raises({exc}): {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _boundary(self, req: Requirement) -> GeneratedTest:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        vi = req.violation_input or {}
        if vi.get("len_check"):
            boundary_call = _inject_short_string(call, str(vi.get("variable", "")))
        else:
            boundary_call = _inject_boundary_value(call, req.description)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {boundary_call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Boundary violation: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _enum(self, req: Requirement) -> GeneratedTest:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Replace the first string arg with an invalid enum value
        enum_call = re.sub(r'"test_value"', '"INVALID_VALUE"', call, count=1)
        if enum_call == call:
            # No string stub to replace — append an invalid kwarg
            enum_call = _append_kwarg(call, 'currency="INVALID_VALUE"')

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {enum_call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Enum violation: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _must_return(self, req: Requirement) -> GeneratedTest | None:
        sig = sig_inspector.inspect(req.target_function, req.target_file)

        # If the return annotation allows None (Optional / X | None),
        # a simple `assert result is not None` will fail on cache-miss / empty
        # inputs — skip and let the report record it as unsupported.
        if sig and _return_is_optional(sig.return_annotation):
            return None

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    {imp}
{setup}    result = {call}
    assert result is not None
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Return not-None: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _not_null(self, req: Requirement) -> GeneratedTest | None:
        # Self-attribute checks (if not self.x:) can't be tested by injecting a param
        if "self." in (req.raw_spec_text or ""):
            return None

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Use violation_input to identify which param to set None
        null_param: str | None = None
        if req.violation_input:
            for k, v in req.violation_input.items():
                if v is None:
                    null_param = k
                    break

        # If the null variable is not an actual kwarg in the generated call, it's a local
        # variable (DB result, computed value, etc.). Use word-boundary check so "user"
        # doesn't false-match inside "user_id=" or "join_team_via_link(...)".
        if null_param and not re.search(rf"\b{re.escape(null_param)}\b\s*=", call):
            return None

        if null_param:
            null_call = re.sub(
                rf"\b{re.escape(null_param)}\s*=\s*[^,)]+",
                f"{null_param}=None",
                call,
                count=1,
            )
            if null_call == call:
                null_call = _append_kwarg(call, f"{null_param}=None")
        else:
            # Replace first string or numeric stub with None
            null_call = re.sub(r'="test_value"', "=None", call, count=1)
            if null_call == call:
                null_call = re.sub(r"=\d+", "=None", call, count=1)
            if null_call == call:
                null_call = _append_kwarg(call, "value=None")

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {null_call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Not-null violation: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _type_check(self, req: Requirement) -> GeneratedTest:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Pass a string where a numeric type is expected
        type_call = re.sub(r"=\d+", '="invalid_type"', call, count=1)
        if type_call == call:
            type_call = _append_kwarg(call, 'value="invalid_type"')

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    with pytest.raises((TypeError, Exception)):
        {type_call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Type check violation: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _silent_fail(self, req: Requirement) -> GeneratedTest | None:
        # Self-attribute silent fails (if not self.x: return None) need class instantiation
        if "self." in (req.raw_spec_text or ""):
            return None

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Replace first string/numeric stub with None or falsy value
        falsy_call = re.sub(r'="test_value"', "=None", call, count=1)
        if falsy_call == call:
            falsy_call = re.sub(r"=\d+", "=0", call, count=1)
        if falsy_call == call:
            falsy_call = _append_kwarg(call, "value=None")

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {req.description}\"\"\"
    import pytest
    {imp}
{setup}    # This function returns None silently instead of raising.
    # The test proves the gap: it should raise but currently doesn't.
    with pytest.raises(Exception):
        {falsy_call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Silent failure — should raise: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )

    def _bug_repro(self, req: Requirement) -> GeneratedTest:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)
        inputs = str(req.violation_input) if req.violation_input else "see description"
        expected = req.expected_behavior or "should not silently accept invalid input"

        code = f"""def {name}{fixture_str}:
    \"\"\"
    Quell bug reproduction: {req.description}
    Triggering input: {inputs}
    Expected: {expected}
    This test FAILS while the bug exists. Fix the code to make it pass.
    \"\"\"
    {imp}
{setup}    import pytest
    with pytest.raises(Exception):
        {call}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Bug reproduction: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )


# ── module-level helpers ──────────────────────────────────────────────────────

def _return_is_optional(annotation: str | None) -> bool:
    """Return True if annotation allows None (Optional[X], X | None, None)."""
    if annotation is None:
        return False
    ann = annotation.strip()
    return (
        ann == "None"
        or ann.startswith(("Optional[", "typing.Optional["))
        or ("|" in ann and "None" in [p.strip() for p in ann.split("|")])
    )


def _inject_short_string(call: str, variable: str) -> str:
    """For len(x) < N boundary guards: replace the variable stub with a 2-char string."""
    if variable:
        # Try named kwarg first: var="test_value" or var=anything
        modified = re.sub(
            rf"\b{re.escape(variable)}\s*=\s*\"[^\"]*\"",
            f'{variable}="ab"',
            call,
            count=1,
        )
        if modified == call:
            modified = re.sub(
                rf"\b{re.escape(variable)}\s*=\s*'[^']*'",
                f"{variable}='ab'",
                call,
                count=1,
            )
        if modified == call:
            modified = re.sub(
                rf"\b{re.escape(variable)}\s*=\s*\w+",
                f'{variable}="ab"',
                call,
                count=1,
            )
        if modified != call:
            return modified
    # Fallback: replace first string stub with a short string
    modified = re.sub(r'"test_value"', '"ab"', call, count=1)
    if modified == call:
        modified = _append_kwarg(call, 'value="ab"')
    return modified


def _append_kwarg(call: str, kwarg: str) -> str:
    """Append a kwarg to a call string without producing `func(, kwarg=val)`."""
    base = call.rstrip(")")
    sep = "" if base.endswith("(") else ", "
    return f"{base}{sep}{kwarg})"


def _inject_boundary_value(call: str, description: str) -> str:
    """Replace the first numeric stub in call with a boundary-violating value."""
    boundary_val = "0"
    desc_lower = description.lower()
    if "positive" in desc_lower or "> 0" in description or "gt=0" in description:
        boundary_val = "0"
    elif ">= 1" in description or "at least 1" in desc_lower or "ge=1" in description:
        boundary_val = "0"
    elif "negative" in desc_lower or "< 0" in description:
        boundary_val = "1"
    elif "between 0 and 1" in desc_lower:
        boundary_val = "-1"
    elif "between 0 and 100" in desc_lower:
        boundary_val = "-1"

    # Replace first integer stub (=1 or =0) with boundary value
    modified = re.sub(r"=\b\d+\b", f"={boundary_val}", call, count=1)
    if modified == call:
        modified = _append_kwarg(call, f"value={boundary_val}")
    return modified
