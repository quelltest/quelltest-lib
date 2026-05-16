"""Unit tests for the 5-gate verification pipeline (spec7 §2.4)."""
from __future__ import annotations

import textwrap

import pytest

from quell.core.gates.gate1_ast import GateContext, check as gate1
from quell.core.gates.gate2_originality import check as gate2
from quell.core.gates.gate3_security import check as gate3
from quell.core.models import (
    BucketedResult,
    ConfidenceTier,
    FlagReason,
    GateResult,
    OutputBucket,
    confidence_tier_for,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_VALID_TEST = textwrap.dedent("""\
    import pytest

    def test_example():
        assert 1 + 1 == 2
""")

_EMPTY_CTX = GateContext()


# ── Gate 1 ────────────────────────────────────────────────────────────────────

class TestGate1:
    def test_valid_python_passes(self):
        result = gate1(_VALID_TEST, _EMPTY_CTX)
        assert result.passed
        assert result.gate == 1

    def test_syntax_error_fails(self):
        result = gate1("def broken(:\n    pass\n", _EMPTY_CTX)
        assert not result.passed
        assert result.gate == 1
        assert "invalid syntax" in (result.reason or "")

    def test_unresolvable_import_fails(self):
        bad = "import totally_nonexistent_package_xyz\n\ndef test_x(): pass\n"
        result = gate1(bad, _EMPTY_CTX)
        assert not result.passed
        assert "unresolvable import" in (result.reason or "")

    def test_stdlib_import_passes(self):
        code = "import json\nimport pathlib\n\ndef test_x():\n    assert True\n"
        result = gate1(code, _EMPTY_CTX)
        assert result.passed

    def test_pytest_import_passes(self):
        result = gate1(_VALID_TEST, _EMPTY_CTX)
        assert result.passed


# ── Gate 2 ────────────────────────────────────────────────────────────────────

class TestGate2:
    def test_novel_test_passes(self):
        result = gate2(_VALID_TEST, _EMPTY_CTX)
        assert result.passed
        assert result.gate == 2

    def test_boilerplate_assertion_fails(self):
        code = textwrap.dedent("""\
            def test_boilerplate():
                result = some_func()
                assert result is not None
        """)
        result = gate2(code, _EMPTY_CTX)
        assert not result.passed
        assert result.gate == 2
        assert "weak" in (result.reason or "")

    def test_duplicate_name_fails(self, tmp_path):
        existing = tmp_path / "test_existing.py"
        existing.write_text("def test_example():\n    assert 1 == 1\n", encoding="utf-8")
        ctx = GateContext(existing_test_files=[str(existing)])
        result = gate2(_VALID_TEST, ctx)
        assert not result.passed
        assert "duplicate" in (result.reason or "")

    def test_no_existing_files_passes(self):
        ctx = GateContext(existing_test_files=[])
        result = gate2(_VALID_TEST, ctx)
        assert result.passed


# ── Gate 3 ────────────────────────────────────────────────────────────────────

class TestGate3:
    def test_clean_test_passes(self):
        result = gate3(_VALID_TEST, _EMPTY_CTX)
        assert result.passed
        assert result.gate == 3

    def test_eval_call_fails(self):
        code = "def test_x():\n    eval('1+1')\n    assert True\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "eval" in (result.reason or "")

    def test_exec_call_fails(self):
        code = "def test_x():\n    exec('x=1')\n    assert True\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "exec" in (result.reason or "")

    def test_os_system_fails(self):
        code = "import os\ndef test_x():\n    os.system('ls')\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "os.system" in (result.reason or "")

    def test_unmocked_requests_fails(self):
        code = "import requests\ndef test_x():\n    requests.get('http://example.com')\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "network" in (result.reason or "")

    def test_hardcoded_password_fails(self):
        code = "def test_x():\n    password = 'supersecret123'\n    assert True\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "credential" in (result.reason or "")

    def test_env_mutation_fails(self):
        code = "import os\ndef test_x():\n    os.environ['SECRET'] = 'val'\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "environ" in (result.reason or "")

    def test_httpx_unmocked_fails(self):
        code = "import httpx\ndef test_x():\n    httpx.get('http://example.com')\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed

    def test_subprocess_shell_true_fails(self):
        code = "import subprocess\ndef test_x():\n    subprocess.Popen(['ls'], shell=True)\n"
        result = gate3(code, _EMPTY_CTX)
        assert not result.passed
        assert "shell=True" in (result.reason or "")


# ── Models ────────────────────────────────────────────────────────────────────

class TestV2Models:
    def test_gate_result_passed(self):
        gr = GateResult(passed=True, gate=1)
        assert gr.passed
        assert gr.gate == 1
        assert gr.reason is None

    def test_gate_result_failed(self):
        gr = GateResult(passed=False, gate=3, reason="security issue")
        assert not gr.passed
        assert gr.reason == "security issue"

    def test_flag_reason_values(self):
        assert FlagReason.EXTERNAL_API == "depends on external API"
        assert FlagReason.GATE4_FAILURE == "test failed on correct code — likely false positive"
        assert FlagReason.GATE5_FAILURE == "test passed even with bug injected — wouldn't catch it"
        assert FlagReason.SECURITY == "generated test failed security review"

    def test_output_bucket_values(self):
        assert OutputBucket.WRITTEN == "WRITTEN"
        assert OutputBucket.SCAFFOLDED == "SCAFFOLDED"
        assert OutputBucket.FLAGGED == "FLAGGED"

    def test_confidence_tier_for(self):
        assert confidence_tier_for(90) == ConfidenceTier.HIGH
        assert confidence_tier_for(85) == ConfidenceTier.HIGH
        assert confidence_tier_for(84) == ConfidenceTier.MEDIUM
        assert confidence_tier_for(60) == ConfidenceTier.MEDIUM
        assert confidence_tier_for(59) == ConfidenceTier.LOW
        assert confidence_tier_for(0) == ConfidenceTier.LOW

    def test_bucketed_result_written(self):
        from quell.core.models import GeneratedTest
        from pathlib import Path
        gt = GeneratedTest(
            requirement_id="req-1",
            test_function_name="test_positive",
            test_code="def test_positive(): assert True",
            test_file_path=Path("tests/test_x.py"),
            explanation="tests boundary",
            generated_by="rule_engine",
        )
        br = BucketedResult(
            requirement_id="req-1",
            bucket=OutputBucket.WRITTEN,
            gates_passed=5,
            generated_test=gt,
            confidence_score=88,
            confidence_tier=ConfidenceTier.HIGH,
        )
        assert br.bucket == OutputBucket.WRITTEN
        assert br.flag_reason is None
        assert br.confidence_score == 88

    def test_bucketed_result_flagged(self):
        br = BucketedResult(
            requirement_id="req-2",
            bucket=OutputBucket.FLAGGED,
            flag_reason=FlagReason.EXTERNAL_API,
            gates_passed=2,
            source_file=None,
        )
        assert br.bucket == OutputBucket.FLAGGED
        assert br.flag_reason == FlagReason.EXTERNAL_API
        assert br.generated_test is None
