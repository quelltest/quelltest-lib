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
import contextlib
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
    SurvivedMutant,
)
from quell.infra.specs import _assert_no_credential_reads

_assert_no_credential_reads()


def _resolve_pytest_cmd() -> list[str]:
    """Return the best available pytest invocation (result is module-cached).

    Priority:
      1. sys.executable -m pytest  — same interpreter as Quell; works when
         pytest is installed in the active venv (the common case).
      2. pytest / py.test from PATH — fallback for conda/system setups where
         quell and pytest live in different environments (e.g. quelltest
         installed in ai_env but pytest only available on PATH).
    """
    global _PYTEST_CMD_CACHE
    if _PYTEST_CMD_CACHE is not None:
        return _PYTEST_CMD_CACHE

    # Fast-path: check if pytest is importable in the current interpreter.
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        capture_output=True,
    )
    if probe.returncode == 0:
        _PYTEST_CMD_CACHE = [sys.executable, "-m", "pytest"]
        return _PYTEST_CMD_CACHE

    # Fallback: find pytest executable anywhere on PATH.
    for exe in ("pytest", "py.test"):
        found = shutil.which(exe)
        if found:
            _PYTEST_CMD_CACHE = [found]
            return _PYTEST_CMD_CACHE

    # Last resort: try anyway and let the error surface naturally.
    _PYTEST_CMD_CACHE = [sys.executable, "-m", "pytest"]
    return _PYTEST_CMD_CACHE


_PYTEST_CMD_CACHE: list[str] | None = None


def _prepend_src_paths(env: dict[str, str], cwd: Path, temp_run_dir: Path | None = None) -> None:
    """Prepend local source trees and optional temp run dir to PYTHONPATH.

    When code lives in src/ (e.g. src/requests/adapters.py), the test
    subprocess must import from there — not from the installed site-packages
    copy — so that Quell's injected violation is actually visible to the test.
    We prepend temp_run_dir (if provided), src/, lib/, and cwd itself;
    whichever exist win over site-packages.
    """
    sep = ";" if sys.platform == "win32" else ":"
    extra = []
    if temp_run_dir:
        extra.append(str(temp_run_dir))
    extra.extend([
        str(p) for p in (cwd / "src", cwd / "lib", cwd)
        if p.is_dir()
    ])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = sep.join(extra + ([existing] if existing else []))


@contextlib.contextmanager
def file_lock(lock_path: Path):
    """Atomic directory-based file locking mechanism."""
    lock_dir = Path(str(lock_path) + ".lock_dir")
    acquired = False
    start_time = time.time()
    while not acquired:
        try:
            lock_dir.mkdir()
            acquired = True
        except FileExistsError:
            if time.time() - start_time > 10:  # 10 seconds timeout
                raise TimeoutError(f"Could not acquire lock on {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


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
        
        # Create a run-specific temp directory for copy-on-write violation
        run_temp_dir = self.backup_dir / f"run_{time.time_ns()}"
        run_temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine relative path from project source root
        cwd = self._resolve_cwd(req.target_file)
        rel_dir = cwd
        for p in (cwd / "src", cwd / "lib"):
            if p.is_dir() and req.target_file.is_relative_to(p):
                rel_dir = p
                break
        rel_path = req.target_file.relative_to(rel_dir)
        temp_target_file = run_temp_dir / rel_path
        
        bak = None
        try:
            # Step 1: test must PASS on correct code
            # Run without prepended temp_run_dir so original workspace code is tested
            orig = self._pytest(temp, req.target_file, temp_run_dir=None)
            if not orig["passed"]:
                combined = (orig.get("stdout", "") or "") + "\n" + (orig.get("stderr", "") or "")
                return VerificationResult(
                    requirement_id=req.id, generated_test=test,
                    status=VerificationStatus.FAILS_ON_CORRECT,
                    error_message=combined.strip(),
                    duration_ms=self._ms(start),
                )

            # Step 2: inject violation into copy
            shutil.copy2(req.target_file, temp_target_file)
            if req.constraint_kind == ConstraintKind.MUTATION:
                # Mutation uses mutmut apply which operates in-place. Lock, backup, apply, copy, restore.
                lock_path = req.target_file.with_suffix(req.target_file.suffix + ".lock")
                with file_lock(lock_path):
                    bak = self._backup(req.target_file)
                    try:
                        subprocess.run(
                            ["mutmut", "apply", req.id],
                            capture_output=True, timeout=10,
                            cwd=req.target_file.parent,
                        )
                        shutil.copy2(req.target_file, temp_target_file)
                    finally:
                        self._restore(req.target_file, bak)
                        bak = None
            else:
                # Run _violate on copy-on-write temp requirement
                temp_req = req.model_copy(update={"target_file": temp_target_file})
                self._violate(temp_req)

            # Step 3: test must FAIL on violated code
            # Prepends run_temp_dir to PYTHONPATH so pytest loads our violated copy
            viol = self._pytest(temp, req.target_file, temp_run_dir=run_temp_dir)
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
            if bak:
                self._restore(req.target_file, bak)
            temp.unlink(missing_ok=True)
            if run_temp_dir.exists():
                shutil.rmtree(run_temp_dir, ignore_errors=True)

    def _write_temp(self, test: GeneratedTest) -> Path:
        d = self.backup_dir / "temp"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"quell_{test.requirement_id}.py"
        f.write_text(test.test_code, encoding="utf-8")
        return f

    def _backup(self, src: Path) -> Path:
        import uuid
        bak = self.backup_dir / f"{src.stem}_{uuid.uuid4().hex}.bak"
        shutil.copy2(src, bak)
        return bak

    def _restore(self, src: Path, bak: Path) -> None:
        try:
            shutil.copy2(bak, src)
            bak.unlink()
        except FileNotFoundError:
            pass

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
        else:
            return

        req.target_file.write_text(modified, encoding="utf-8")

    def _pytest(self, test_file: Path, src: Path, temp_run_dir: Path | None = None) -> dict:  # type: ignore[type-arg]
        # Run from project root so all package imports resolve correctly.
        cwd = self._resolve_cwd(src)
        env = os.environ.copy()
        env.update(_load_dotenv(cwd))
        _prepend_src_paths(env, cwd, temp_run_dir)
        env.setdefault("QUELL_TRANSACTION_ROLLBACK", "false")
        cmd = _resolve_pytest_cmd()
        try:
            r = subprocess.run(
                cmd + [str(test_file), "-v", "--tb=short", "-q", "--no-header"],
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
    """Merge KEY=VALUE pairs from every dotenv-family file at `cwd`."""
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
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
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

def _func_line_range(src: str, func_name: str) -> tuple[int, int] | None:
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
    rng = _func_line_range(src, func_name)
    if rng is None:
        return re.sub(pattern, replacement, src, count=count)

    lines = src.splitlines(keepends=True)
    start, end = rng[0] - 1, rng[1]
    func_block = "".join(lines[start:end])
    modified_block = re.sub(pattern, replacement, func_block, count=count)
    return "".join(lines[:start]) + modified_block + "".join(lines[end:])


def _violate_must_raise(src: str, func_name: str) -> str:
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
        elif isinstance(node, _ast.Assert):
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
        lambda m: m.group(1) + "-9999",
    )


def _violate_must_return(src: str, func_name: str) -> str:
    return _violate_in_range(
        src, func_name,
        r'return (?!None\b)',
        'return None  # QUELL_VIOLATION ',
        count=0,
    )


def _violate_silent_fail(src: str, func_name: str) -> str:
    return _violate_in_range(
        src, func_name,
        r'\breturn(?:\s+None\b|\s*(?=#[^\n]*\n|\n|$))',
        'raise ValueError("quell_violation")',
        count=1,
    )


class MutantVerifier(Verifier):
    """Subclass of Verifier specifically for mutation testing verification."""

    def verify(
        self, mutant: SurvivedMutant, test: GeneratedTest
    ) -> VerificationResult:
        """Verify a test kills a mutant. Maps SurvivedMutant to a Requirement."""
        from quell.core.models import Requirement, ConstraintKind, SpecSource
        req = Requirement(
            id=mutant.id,
            description=f"Kill mutant {mutant.id}",
            constraint_kind=ConstraintKind.MUTATION,
            source=SpecSource.MUTATION,
            target_function=mutant.function_name or "",
            target_file=mutant.file_path,
        )
        return super().verify(req, test)
