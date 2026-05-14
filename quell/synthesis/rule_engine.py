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
            ConstraintKind.MAGIC_VALUE,
            ConstraintKind.CUSTOM,
        }

    def generate(self, req: Requirement) -> GeneratedTest | None:
        if self._all_required_unknown(req):
            return None  # all required params are complex objects → no useful stub
        if req.constraint_kind == ConstraintKind.MUST_RAISE:
            return self._must_raise(req)
        if req.constraint_kind == ConstraintKind.BOUNDARY:
            return self._boundary(req)
        if req.constraint_kind == ConstraintKind.ENUM_VALID:
            return self._enum(req)
        if req.constraint_kind == ConstraintKind.MAGIC_VALUE:
            return self._magic_value(req)
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
        if req.constraint_kind == ConstraintKind.CUSTOM:
            return self._custom(req)
        return None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _safe_desc(self, req: Requirement) -> str:
        """Return description safe to embed inside a triple-double-quote docstring.

        Descriptions that end with a double-quote break the closing delimiter.
        Replacing all double-quotes with single-quotes prevents the SyntaxError.
        """
        return req.description.replace('"', "'")

    def _test_file(self, req: Requirement) -> Path:
        return _project_root(req.target_file) / "tests" / f"test_{req.target_file.stem}.py"

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
            return call, "()", fixtures, [f"sig_not_found:{func}"]

        call_args, fixtures, unknown = sig_inspector.stub_for_call(sig)

        if sig.is_method and sig.class_name:
            if sig.is_classmethod:
                # Classmethods (including Pydantic @validator): call on the class directly,
                # Python auto-passes cls — no construction needed, no Pydantic validation.
                call = f"{sig.class_name}.{func}({call_args})"
            else:
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

    def _is_async(self, req: Requirement) -> bool:
        """Return True if the target function is async def."""
        sig = sig_inspector.inspect(req.target_function, req.target_file)
        return sig is not None and sig.is_async

    def _all_required_unknown(self, req: Requirement) -> bool:
        """Return True when every required param is an unknown type.

        Stub resolution falls back to None for unknown types. A function like
        send(request: PreparedRequest) becomes send(request=None) which crashes
        on request.url before reaching any guard — wasting two pytest runs.
        Skip these early so the report shows skipped_local_var (complex param)
        instead of rejected_fails_on_correct with an unhelpful AttributeError.
        """
        sig = sig_inspector.inspect(req.target_function, req.target_file)
        if sig is None or not sig.required_params:
            return False
        _, _, unknown = sig_inspector.stub_for_call(sig)
        # If every required param is unknown, the stub is all-None → useless
        return len(unknown) >= len(sig.required_params)

    def _wrap_call(self, call: str, req: Requirement) -> str:
        """Wrap a call expression with asyncio.run(...) if the target is async.
        Sync stub calls on `async def` return a coroutine (no exception),
        so the test must drive the coroutine for guards to actually fire.
        """
        return f"asyncio.run({call})" if self._is_async(req) else call

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
            candidate = m.group(1)
            # Only use the extracted name if it's a builtin exception — otherwise
            # the test file would reference it without an import and get NameError.
            # Project-specific exceptions (e.g. ProxyError, LocationValueError)
            # need an import we can't always resolve statically; use Exception as
            # the safe fallback so the test at least runs without NameError.
            if candidate in _BUILTIN_EXCEPTIONS:
                exc = candidate

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = ""
        name = self._name(req)
        wrapped = self._wrap_call(call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises({exc}):
        {wrapped}
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

    def _boundary(self, req: Requirement) -> GeneratedTest | None:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        vi = req.violation_input or {}
        if vi.get("len_check"):
            boundary_call = _inject_short_string(call, str(vi.get("variable", "")))
        else:
            boundary_call = _inject_boundary_value(call, req.description)
        wrapped = self._wrap_call(boundary_call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {wrapped}
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

    def _enum(self, req: Requirement) -> GeneratedTest | None:
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Replace the first string arg with an invalid enum value
        enum_call = re.sub(r'"test_value"', '"INVALID_VALUE"', call, count=1)
        if enum_call == call:
            # No string stub to replace — append an invalid kwarg using the actual variable name
            vi = req.violation_input or {}
            enum_var = str(vi.get("variable", "value"))
            enum_call = _append_kwarg(call, f'{enum_var}="INVALID_VALUE"')
        wrapped = self._wrap_call(enum_call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {wrapped}
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

    def _magic_value(self, req: Requirement) -> GeneratedTest | None:
        """Test `if x == "MAGIC": raise` patterns by passing a non-magic value."""
        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)

        # Try to extract the variable name from the guard (left side of comparison)
        raw = req.raw_spec_text or ""
        m = re.search(r"if\s+(\w+)\s*(?:==|!=)\s*", raw)
        var_name = m.group(1) if m else "value"

        # Replace existing kwarg for the variable, else append
        magic_call = re.sub(
            rf"\b{re.escape(var_name)}\s*=\s*[^,)]+",
            f'{var_name}="QUELL_NOT_MAGIC"',
            call,
            count=1,
        )
        if magic_call == call:
            magic_call = re.sub(r'"test_value"', '"QUELL_NOT_MAGIC"', call, count=1)
        if magic_call == call:
            magic_call = _append_kwarg(call, f'{var_name}="QUELL_NOT_MAGIC"')
        wrapped = self._wrap_call(magic_call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {wrapped}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Magic-value violation: {req.description}",
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

        wrapped = self._wrap_call(call, req)
        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    {imp}
{setup}    result = {wrapped}
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
            # Only append if the param isn't already =None (prevents duplicate kwargs)
            if null_call == call and f"{null_param}=None" not in call:
                null_call = _append_kwarg(call, f"{null_param}=None")
        else:
            # Replace first string or numeric stub with None
            null_call = re.sub(r'="test_value"', "=None", call, count=1)
            if null_call == call:
                null_call = re.sub(r"=\d+", "=None", call, count=1)
            if null_call == call and "=None" not in call:
                null_call = _append_kwarg(call, "value=None")

        wrapped = self._wrap_call(null_call, req)
        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {wrapped}
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
        wrapped = self._wrap_call(type_call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises((TypeError, Exception)):
        {wrapped}
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

        # Replace first stub value with None/falsy. Try in order of specificity so
        # we hit the most likely guard variable first and never produce a duplicate kwarg.
        falsy_call = re.sub(r'="test_value"', "=None", call, count=1)
        if falsy_call == call:
            falsy_call = re.sub(r"=\d+", "=None", call, count=1)
        # Also handle collection stubs ({}, [], (), set()) — e.g. value: dict
        for coll_pat in (r"=\{\}", r"=\[\]", r"=\(\)", r"=set\(\)"):
            if falsy_call != call:
                break
            falsy_call = re.sub(coll_pat, "=None", call, count=1)
        if falsy_call == call:
            # Try to replace the specific guard variable from violation_input
            if req.violation_input:
                for k in req.violation_input:
                    if re.search(rf"\b{re.escape(k)}\s*=", call):
                        falsy_call = re.sub(
                            rf"\b{re.escape(k)}\s*=\s*[^,)]+",
                            f"{k}=None",
                            call,
                            count=1,
                        )
                        break
        if falsy_call == call and "=None" not in call:
            # Only append if there's no existing None stub and no param was found above
            falsy_call = _append_kwarg(call, "value=None")

        wrapped = self._wrap_call(falsy_call, req)
        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: silent failure gap — {self._safe_desc(req)} (should raise, currently returns None)\"\"\"
    import asyncio
    {imp}
{setup}    result = {wrapped}
    assert result is None  # documents silent return — gap: should raise but doesn't
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
        wrapped = self._wrap_call(call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"
    Quell bug reproduction: {self._safe_desc(req)}
    Triggering input: {inputs}
    Expected: {expected}
    This test FAILS while the bug exists. Fix the code to make it pass.
    \"\"\"
    import asyncio
    {imp}
{setup}    import pytest
    with pytest.raises(Exception):
        {wrapped}
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

    def _custom(self, req: Requirement) -> GeneratedTest | None:
        """Fallback generator for CUSTOM guards (compound conditions, asserts, etc.).

        Generates a pytest.raises(Exception) test. The verifier will reject it if
        the guard can't be triggered — only genuinely provable guards pass through.
        """
        if "self." in (req.raw_spec_text or ""):
            return None  # attribute guards need class instantiation we can't stub

        call, fixture_str, fixtures, unknown = self._sig_info(req)
        imp = self._import_line(req)
        setup = self._setup_lines(fixtures)
        name = self._name(req)
        wrapped = self._wrap_call(call, req)

        code = f"""def {name}{fixture_str}:
    \"\"\"Quell: {self._safe_desc(req)}\"\"\"
    import asyncio
    import pytest
    {imp}
{setup}    with pytest.raises(Exception):
        {wrapped}
"""
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=self._test_file(req),
            explanation=f"Custom guard: {req.description}",
            generated_by="rule_engine",
            unknown_types=unknown,
        )


# ── module-level helpers ──────────────────────────────────────────────────────

# Python builtin exception names that are always in scope — no import needed.
# Any exception class NOT in this set comes from a library and needs an import
# we can't safely synthesise, so we fall back to `Exception`.
_BUILTIN_EXCEPTIONS: frozenset[str] = frozenset({
    "Exception", "BaseException", "ArithmeticError", "AssertionError",
    "AttributeError", "BlockingIOError", "BrokenPipeError", "BufferError",
    "BytesWarning", "ChildProcessError", "ConnectionAbortedError",
    "ConnectionError", "ConnectionRefusedError", "ConnectionResetError",
    "DeprecationWarning", "EOFError", "EnvironmentError", "FileExistsError",
    "FileNotFoundError", "FloatingPointError", "FutureWarning", "GeneratorExit",
    "IOError", "ImportError", "ImportWarning", "IndentationError", "IndexError",
    "InterruptedError", "IsADirectoryError", "KeyError", "KeyboardInterrupt",
    "LookupError", "MemoryError", "ModuleNotFoundError", "NameError",
    "NotADirectoryError", "NotImplementedError", "OSError", "OverflowError",
    "PendingDeprecationWarning", "PermissionError", "ProcessLookupError",
    "RecursionError", "ReferenceError", "ResourceWarning", "RuntimeError",
    "RuntimeWarning", "StopAsyncIteration", "StopIteration", "SyntaxError",
    "SyntaxWarning", "SystemError", "SystemExit", "TabError", "TimeoutError",
    "TypeError", "UnboundLocalError", "UnicodeDecodeError", "UnicodeEncodeError",
    "UnicodeError", "UnicodeTranslateError", "UnicodeWarning", "UserWarning",
    "ValueError", "Warning", "ZeroDivisionError",
})


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


def _project_root(file_path: Path) -> Path:
    """Walk up from file_path to find the project root.

    Looks for pyproject.toml, setup.py, setup.cfg, or .git as markers.
    Falls back to two levels up (original behaviour) if none found.
    """
    markers = {"pyproject.toml", "setup.py", "setup.cfg", ".git"}
    current = file_path.parent
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent
    return file_path.parent.parent
