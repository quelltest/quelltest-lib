"""Generate TestClient-based tests for framework route handlers.

The rule engine is great for pure functions (validators, parsers). For
FastAPI/Flask routes it can't drive `Depends()` injection or async DB calls,
so we use the framework's own test client instead. Verification still
applies — we run the test once on correct code, comment out the guard's
raise, run it again, and only keep it if the violation flips the outcome.
"""
from __future__ import annotations

import re
from pathlib import Path

from quell.core.models import ConstraintKind, GeneratedTest, Requirement
from quell.synthesis.app_locator import AppInfo
from quell.synthesis.framework_detector import RouteInfo


class FrameworkEngine:
    """TestClient-based generator for framework routes."""

    def can_handle(self, route: RouteInfo | None, app: AppInfo | None) -> bool:
        if route is None or app is None:
            return False
        if route.framework != app.framework:
            return False
        # FastAPI only for the MVP; Flask test stubs are a separate problem.
        return route.framework == "fastapi"

    def generate(
        self,
        req: Requirement,
        route: RouteInfo,
        app: AppInfo,
    ) -> GeneratedTest | None:
        """Build a TestClient test that exercises the route with violating input."""
        path = self._substitute_path(route.path, req)
        method = route.method.lower()
        # POST/PUT/PATCH need a body; for now use an empty dict — the guard
        # we're testing usually fires on a missing/invalid field, so empty
        # is often enough to trigger the violation.
        body_kwarg = ", json={}" if method in {"post", "put", "patch"} else ""
        name = self._test_name(req)
        test_file = self._test_file(req)

        code = (
            f"def {name}():\n"
            f'    """Quell (framework): {req.description}"""\n'
            f"    from fastapi.testclient import TestClient\n"
            f"    from {app.module_path} import {app.attr_name}\n"
            f"    client = TestClient({app.attr_name})\n"
            f'    response = client.{method}("{path}"{body_kwarg})\n'
            f"    # The guard should produce a 4xx error response.\n"
            f"    assert response.status_code >= 400\n"
        )
        return GeneratedTest(
            requirement_id=req.id,
            test_function_name=name,
            test_code=code,
            test_file_path=test_file,
            explanation=(
                f"TestClient {method.upper()} {path} — expect 4xx when guard fires"
            ),
            generated_by="framework_engine",
            unknown_types=[],
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _substitute_path(self, path: str, req: Requirement) -> str:
        """Replace {param} placeholders with values that trigger the guard.

        For MAGIC_VALUE we extract the literal from the guard ('if x == "X":')
        and pass that string so the raise actually fires.
        For BOUNDARY we use 0 (works for `< N` / `<= N` with N>=0).
        For ENUM/NOT_NULL on a path param we use a sentinel that's unlikely
        to match any valid enum but is still a non-empty path segment.
        """
        kind = req.constraint_kind
        vi = req.violation_input or {}
        magic = self._extract_magic_literal(req.raw_spec_text or "")

        def repl(match: re.Match[str]) -> str:
            param = match.group(1).split(":")[0]
            if kind == ConstraintKind.MAGIC_VALUE and magic is not None:
                return magic
            if param in vi:
                v = vi[param]
                if v is None:
                    return "0"
                return str(v)
            if kind == ConstraintKind.BOUNDARY:
                return "0"
            if kind in (ConstraintKind.ENUM_VALID, ConstraintKind.MAGIC_VALUE):
                return "QUELL_INVALID"
            return "invalid"

        return re.sub(r"\{([^}]+)\}", repl, path)

    @staticmethod
    def _extract_magic_literal(guard: str) -> str | None:
        """Pull the string literal out of `if x == "X":` / `if x != "X":`."""
        m = re.search(r"""(==|!=)\s*['"]([^'"]+)['"]""", guard)
        return m.group(2) if m else None

    def _test_name(self, req: Requirement) -> str:
        func = re.sub(r"[^a-z0-9_]", "_", req.target_function.lower())
        return f"test_quell_fw_{func}_{req.constraint_kind.value}_{req.id[:8]}"

    def _test_file(self, req: Requirement) -> Path:
        from quell.synthesis.rule_engine import _project_root
        return _project_root(req.target_file) / "tests" / f"test_{req.target_file.stem}.py"
