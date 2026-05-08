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
import subprocess, shutil, time, re
from pathlib import Path
from quell.core.models import (
    Requirement, GeneratedTest, VerificationResult,
    VerificationStatus, ConstraintKind, QuellConfig,
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
                return VerificationResult(
                    requirement_id=req.id, generated_test=test,
                    status=VerificationStatus.FAILS_ON_CORRECT,
                    error_message=orig.get("stderr", ""),
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
        f.write_text(test.test_code)
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

        src = req.target_file.read_text()

        if req.constraint_kind == ConstraintKind.MUST_RAISE:
            modified = re.sub(
                r'(\s+)(raise \w+)', r'\1# QUELL_VIOLATION \2', src, count=1
            )
        elif req.constraint_kind == ConstraintKind.BOUNDARY:
            modified = re.sub(
                r'((?:>|>=|<|<=)\s*)(\d+)',
                lambda m: m.group(1) + "-9999",
                src, count=1,
            )
        elif req.constraint_kind == ConstraintKind.MUST_RETURN:
            modified = re.sub(
                r'return (?!None)', 'return None  # QUELL_VIOLATION ', src, count=1
            )
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
            return  # CUSTOM — LLM handles injection in llm_engine

        req.target_file.write_text(modified)

    def _pytest(self, test_file: Path, src: Path) -> dict:  # type: ignore[type-arg]
        # Run from project root so all package imports resolve correctly.
        # Fall back to sig_inspector's finder, then src.parent.parent.
        cwd = self._resolve_cwd(src)
        try:
            r = subprocess.run(
                ["python", "-m", "pytest", str(test_file),
                 "-v", "--tb=short", "-q", "--no-header"],
                capture_output=True, text=True,
                timeout=self.config.verification_timeout_seconds,
                cwd=cwd,
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
