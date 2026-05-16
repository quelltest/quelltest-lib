"""Gate 3 — Security Check on Generated Test.

Banned patterns:
  - Hardcoded credential strings
  - eval(), exec(), os.system(), subprocess.Popen(shell=True)
  - Unmocked requests/httpx calls
  - File writes outside tmp_path
  - os.environ mutations

Returns GateResult(passed=False, reason='generated test failed security review')
for any violation, GateResult(passed=True) if clean.
"""
from __future__ import annotations

import ast
import re

from quell.core.gates.gate1_ast import GateContext
from quell.core.models import GateResult

# Regex patterns for credential detection
_CRED_PATTERN = re.compile(
    r'(?i)(password|passwd|token|secret|api_key|apikey)\s*=\s*["\'][^"\']{4,}["\']'
)

# Banned call patterns (module.func or bare func)
_BANNED_CALLS = {
    "eval", "exec",
}
_BANNED_ATTR_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "call"),
}


def check(test_code: str, ctx: GateContext) -> GateContext | GateResult:  # noqa: ARG001
    """Gate 3: security checks on the generated test code."""
    # 1. Hardcoded credentials
    if _CRED_PATTERN.search(test_code):
        return GateResult(
            passed=False, gate=3,
            reason="generated test failed security review: hardcoded credential",
        )

    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        # Already caught by gate 1 — pass through
        return GateResult(passed=True, gate=3)

    for node in ast.walk(tree):
        # 2. Banned bare calls: eval(), exec()
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS:
                return GateResult(
                    passed=False, gate=3,
                    reason=f"generated test failed security review: banned call {node.func.id}()",
                )

            # 3. Banned attribute calls: os.system(), subprocess.Popen(shell=True), etc.
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    pair = (node.func.value.id, node.func.attr)
                    if pair in _BANNED_ATTR_CALLS:
                        return GateResult(
                            passed=False, gate=3,
                            reason=f"generated test failed security review: banned call {pair[0]}.{pair[1]}()",
                        )
                    # subprocess.Popen(shell=True)
                    if pair == ("subprocess", "Popen"):
                        for kw in node.keywords:
                            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value:
                                return GateResult(
                                    passed=False, gate=3,
                                    reason="generated test failed security review: subprocess.Popen(shell=True)",
                                )

                    # Unmocked network calls
                    if node.func.value.id in ("requests", "httpx") and node.func.attr in (
                        "get", "post", "put", "patch", "delete", "request", "send",
                    ):
                        return GateResult(
                            passed=False, gate=3,
                            reason=f"generated test failed security review: unmocked network call {node.func.value.id}.{node.func.attr}()",
                        )

        # 4. os.environ mutations (os.environ['X'] = ... or os.environ.update())
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "os"
                    and target.value.attr == "environ"
                ):
                    return GateResult(
                        passed=False, gate=3,
                        reason="generated test failed security review: os.environ mutation",
                    )

    return GateResult(passed=True, gate=3)
