"""
Verification Engine — the core technical moat.

This is what separates Quell from every competitor:
  Qodo generates tests. Quell PROVES them.
  Copilot suggests tests. Quell VERIFIES them.

Algorithm:
  1. Write candidate test to TEMP file (not real test file)
  2. Run test on ORIGINAL source → MUST PASS
     (if it fails, the test is wrong — bad test, reject)
  3. Inject VIOLATION into source (break the requirement)
  4. Run test on VIOLATED source → MUST FAIL
     (if it passes, test doesn't catch the bug — weak test, reject)
  5. ALWAYS restore source in finally block
  6. Return VerificationResult

Violation injection per ConstraintKind:
  MUST_RAISE:   comment out the raise statement
  BOUNDARY:     weaken threshold (> 0 → > -9999)
  ENUM_VALID:   remove the enum validation guard
  MUST_RETURN:  change return value to None
  BUG_REPRO:    no injection needed — source is already broken
  MUTATION:     use mutmut apply or direct line replacement

ABSOLUTE RULES — never violate:
- ALWAYS restore source in finally block
- ALWAYS use subprocess for pytest — never in-process (module cache)
- NEVER skip verification for performance — optimize test speed instead
- NEVER add --skip-verification flag
"""
from __future__ import annotations

import ast as _ast
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from quell.core.models import (
    ConstraintKind,
    GeneratedTest,
    QuellConfig,
    Requirement,
    VerificationResult,
    VerificationStatus,
)


class Verifier:
    """Proves every generated test actually catches violations before writing."""

    def __init__(self, config: QuellConfig, project_root: Path | None = None):
        self.config = config
        self.backup_dir = config.backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._project_root = project_root

    def verify(
        self, req: Requirement, test: GeneratedTest
    ) -> VerificationResult:
        """Run full two-phase verification. Always restores source in finally."""
        start = time.time()
        temp = self._write_temp(test)
        bak = self._backup(req.target_file)

        try:
            # Step 1: test must PASS on correct code
            orig = self._pytest(temp, req.target_file)
            if not orig["passed"]:
                # pytest writes failure details to stdout in --tb=short mode;
                # stderr is mostly empty unless the subprocess itself crashed.
                # Capture both so the diagnostic surfaces the real reason
                # (ImportError, missing env var, app startup failure, etc.).
                combined = (orig.get("stdout", "") or "") + "\n" + (orig.get("stderr", "") or "")
                return VerificationResult(
                    requirement_id=req.id, generated_test=test,
                    status=VerificationStatus.FAILS_ON_CORRECT,
                    error_message=combined.strip(),
                    duration_ms=self._ms(start),
                )

            # Step 2: inject violation
            self._violate(req)

            # Step 3: test must FAIL on violated code
            viol = self._pytest(temp, req.target_file)
            status = (
                VerificationStatus.VERIFIED if not viol["passed"]
                else VerificationStatus.DOESNT_CATCH_VIOLATION
            )
            return VerificationResult(
                requirement_id=req.id, generated_test=test,
                status=status,
                duration_ms=self._ms(start),
            )

        except TimeoutError:
            return VerificationResult(
                requirement_id=req.id, generated_test=test,
                status=VerificationStatus.TIMEOUT,
                duration_ms=self.config.verification_timeout_seconds * 1000,
            )
        except Exception as e:
            return VerificationResult(
                requirement_id=req.id, generated_test=test,
                status=VerificationStatus.ERROR,
                error_message=str(e),
                duration_ms=self._ms(start),
            )
        finally:
            # ALWAYS restore — no exceptions to this rule
            self._restore(req.target_file, bak)
            temp.unlink(missing_ok=True)

    def _write_temp(self, test: GeneratedTest) -> Path:
        d = self.backup_dir / "temp"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"quell_{test.requirement_id}.py"
        # CRITICAL: utf-8 explicitly. On Windows, Path.write_text() defaults to
        # cp1252; Python source is utf-8 (PEP 3120). Em-dashes in Quell
        # descriptions become byte 0x97 in cp1252, which is invalid utf-8 — pytest
        # then fails to parse the file and the test reports FAILS_ON_CORRECT for
        # the wrong reason. This single line is the difference between
        # verified=0 and verified>0 on Windows.
        f.write_text(test.test_code, encoding="utf-8")
        return f

    def _backup(self, src: Path) -> Path:
        bak = self.backup_dir / f"{src.stem}_{int(time.time())}.bak"
        shutil.copy2(src, bak)
        return bak

    def _restore(self, src: Path, bak: Path) -> None:
        if bak.exists():
            shutil.copy2(bak, src)
            bak.unlink()

    def _violate(self, req: Requirement) -> None:
        """Modify source to break the requirement so a good test will fail."""
        if req.constraint_kind == ConstraintKind.BUG_REPRO:
            return  # already broken

        src = req.target_file.read_text(encoding="utf-8")

        # All kinds whose test asserts `pytest.raises(...)` need the function's
        # raises commented out to break the guard. Without this, step 3 runs
        # the same code and the test passes again → DOESNT_CATCH_VIOLATION.
        raise_based = {
            ConstraintKind.MUST_RAISE,
            ConstraintKind.NOT_NULL,
            ConstraintKind.ENUM_VALID,
            ConstraintKind.TYPE_CHECK,
            ConstraintKind.AUTH_CHECK,
            ConstraintKind.MAGIC_VALUE,
            ConstraintKind.CUSTOM,
        }
        if req.constraint_kind in raise_based:
            modified = _violate_must_raise(src, req.target_function)
        elif req.constraint_kind == ConstraintKind.BOUNDARY:
            modified = _violate_boundary(src, req.target_function)
        elif req.constraint_kind == ConstraintKind.MUST_RETURN:
            modified = _violate_must_return(src, req.target_function)
        elif req.constraint_kind == ConstraintKind.SILENT_FAIL:
            modified = _violate_silent_fail(src, req.target_function)
        elif req.constraint_kind == ConstraintKind.MUTATION:
            try:
                subprocess.run(
                    ["mutmut", "apply", req.id],
                    capture_output=True, timeout=10,
                    cwd=req.target_file.parent,
                )
            except Exception:
                pass
            return
        else:
            return

        req.target_file.write_text(modified, encoding="utf-8")

    def _pytest(self, test_file: Path, src: Path) -> dict:  # type: ignore[type-arg]
        # Run from project root so all package imports resolve correctly.
        # Fall back to sig_inspector's finder, then src.parent.parent.
        cwd = self._resolve_cwd(src)
        # Build env: start from the parent shell's env (which subprocess would
        # inherit by default), then layer in any .env file at the project root.
        # This makes Quell behave like the user running `python -m pytest`
        # themselves after a normal shell + dotenv setup. Nothing leaves the
        # machine — this is the same env the user already has access to.
        env = os.environ.copy()
        env.update(_load_dotenv(cwd))
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file),
                 "-v", "--tb=short", "-q", "--no-header"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.config.verification_timeout_seconds,
                cwd=cwd,
                env=env,
            )
            return {
                "passed": r.returncode == 0,
                "stdout": r.stdout,
                "stderr": r.stderr,
            }
        except subprocess.TimeoutExpired:
            raise TimeoutError()

    def _resolve_cwd(self, src: Path) -> Path:
        """Find the correct working directory for pytest subprocess."""
        if self._project_root and self._project_root.exists():
            return self._project_root
        # Walk up to find pyproject.toml / setup.py
        markers = {"pyproject.toml", "setup.py", "setup.cfg"}
        current = src.parent
        while current != current.parent:
            if any((current / m).exists() for m in markers):
                return current
            current = current.parent
        return src.parent.parent

    def _ms(self, start: float) -> int:
        return int((time.time() - start) * 1000)


# ── env handling ─────────────────────────────────────────────────────────────

# Files we try, in order of *lowest* to *highest* priority. Templates and
# examples are loaded first so they fill in placeholder values for any var
# the user hasn't set elsewhere; the real .env files override them.
# Rationale: a template that says `MONGODB_URI=changeme` is enough to let
# pydantic-settings instantiate at app import — better than KeyError, even
# if the value can't actually connect anywhere.
_DOTENV_CANDIDATES: tuple[str, ...] = (
    ".env.template",
    ".env.example",
    ".env.sample",
    ".env.dist",
    ".secrets",
    ".env.local",
    ".env.development",
    ".env.dev",
    ".env",
)


def _load_dotenv(cwd: Path) -> dict[str, str]:
    """Merge KEY=VALUE pairs from every dotenv-family file at `cwd`.

    Later files in `_DOTENV_CANDIDATES` override earlier ones, so real
    `.env` wins over `.env.example`. Minimal in-tree parser — no
    python-dotenv dependency. Returns {} if nothing readable found.
    Never raises.
    """
    merged: dict[str, str] = {}
    for name in _DOTENV_CANDIDATES:
        path = cwd / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        merged.update(_parse_dotenv(text))
    return merged


def _parse_dotenv(text: str) -> dict[str, str]:
    """Parse one dotenv file's contents. Accepts KEY=VALUE, KEY="V", KEY='V'."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Allow `export FOO=bar` (some teams write .env this way)
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        # Strip an inline comment that isn't inside quotes
        if value and value[0] not in ("'", '"'):
            hash_pos = value.find(" #")
            if hash_pos != -1:
                value = value[:hash_pos].rstrip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        out[key] = value
    return out


# ── targeted violation helpers ────────────────────────────────────────────────
# Each helper targets ONLY the lines inside the named function, not the whole
# file. This prevents the verifier from accidentally violating a different
# function when multiple functions share the same pattern.

def _func_line_range(src: str, func_name: str) -> tuple[int, int] | None:
    """Return (start_line, end_line) for func_name in src (1-indexed, inclusive)."""
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            if node.name == func_name:
                end = getattr(node, "end_lineno", None)
                if end:
                    return (node.lineno, end)
    return None


def _violate_in_range(
    src: str,
    func_name: str,
    pattern: str,
    replacement: str,
    count: int = 1,
) -> str:
    """Apply re.sub only within the lines of func_name."""
    rng = _func_line_range(src, func_name)
    if rng is None:
        # Fallback: file-wide replacement (original behaviour)
        return re.sub(pattern, replacement, src, count=count)

    lines = src.splitlines(keepends=True)
    start, end = rng[0] - 1, rng[1]  # convert to 0-indexed
    func_block = "".join(lines[start:end])
    modified_block = re.sub(pattern, replacement, func_block, count=count)
    return "".join(lines[:start]) + modified_block + "".join(lines[end:])


def _violate_must_raise(src: str, func_name: str) -> str:
    """Replace every `raise X(...)` in func_name with `pass`.

    AST-based — handles multi-line raises and never leaves an empty `if:` block.
    Commenting out a raise (the old behaviour) produced IndentationError because
    a bare comment doesn't satisfy Python's block requirement.
    Replacing with `pass` keeps the syntax valid and breaks the guard so the
    test's `pytest.raises(...)` no longer triggers.
    """
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return src

    target = None
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            if node.name == func_name:
                target = node
                break
    if target is None:
        return src

    spans: list[tuple[int, int]] = []
    for node in _ast.walk(target):
        if isinstance(node, _ast.Raise):
            start = node.lineno - 1
            end = (node.end_lineno or node.lineno) - 1
            spans.append((start, end))
    if not spans:
        return src

    lines = src.splitlines(keepends=True)
    for start, end in sorted(spans, key=lambda s: -s[0]):
        if start >= len(lines):
            continue
        line = lines[start]
        indent = line[: len(line) - len(line.lstrip())]
        if line.endswith("\r\n"):
            eol = "\r\n"
        elif line.endswith("\n"):
            eol = "\n"
        else:
            eol = ""
        lines[start:end + 1] = [f"{indent}pass  # QUELL_VIOLATION{eol}"]
    return "".join(lines)


def _violate_boundary(src: str, func_name: str) -> str:
    return _violate_in_range(
        src, func_name,
        r'((?:>|>=|<|<=)\s*)(\d+)',
        lambda m: m.group(1) + "-9999",  # type: ignore[arg-type]
    )


def _violate_must_return(src: str, func_name: str) -> str:
    # Replace ALL non-None returns so early-return paths are also violated.
    return _violate_in_range(
        src, func_name,
        r'return (?!None\b)',
        'return None  # QUELL_VIOLATION ',
        count=0,
    )


def _violate_silent_fail(src: str, func_name: str) -> str:
    # Change the first silent `return None` to a raise so the gap test fails.
    return _violate_in_range(
        src, func_name,
        r'\breturn None\b',
        'raise ValueError("quell_violation")',
        count=1,
    )
