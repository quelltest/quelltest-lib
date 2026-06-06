"""Unit tests for the quell.sync module (issues #103–#105, spec8 §11.2–11.3)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quell.sync.models import EdgeCaseCounts, SyncPayload, WrittenTestMeta
from quell.sync.payload import build_sync_payload
from quell.sync.sanitizer import SanitizationError, sanitize

# ── SyncPayload schema ─────────────────────────────────────────────────────────

def test_sync_payload_round_trips_json() -> None:
    import datetime
    payload = SyncPayload(
        project_id="abc123",
        project_alias="payments-service",
        run_at=datetime.datetime(2026, 6, 6, 12, 0, 0, tzinfo=datetime.UTC),
        quell_version="2.0.1",
        prs=71,
        prs_delta=12,
        edge_cases=EdgeCaseCounts(total=23, written=8, scaffolded=3, flagged=2),
        written_tests=[
            WrittenTestMeta(
                name="test_payment_rejects_zero_amount",
                confidence=94,
                tier="HIGH",
                file="tests/test_payments.py",
                edge_case_type="BOUNDARY",
                spec_source="pydantic",
            )
        ],
    )
    dumped = payload.model_dump(mode="json")
    restored = SyncPayload.model_validate(dumped)
    assert restored.prs == 71
    assert restored.written_tests[0].confidence == 94


def test_sync_payload_confidence_bounds() -> None:
    with pytest.raises(Exception):
        WrittenTestMeta(
            name="t", confidence=101, tier="HIGH",
            file="f", edge_case_type="BOUNDARY", spec_source="pydantic",
        )


# ── sanitizer ─────────────────────────────────────────────────────────────────

def _valid_payload_dict() -> dict:
    import datetime
    return {
        "project_id": "abc",
        "project_alias": "svc",
        "run_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC).isoformat(),
        "quell_version": "2.0.1",
        "prs": 71,
        "prs_delta": 0,
        "edge_cases": {"total": 1, "written": 1, "scaffolded": 0, "flagged": 0},
        "written_tests": [],
        "scaffolded_items": [],
        "flagged_items": [],
    }


def test_sanitizer_accepts_valid_payload() -> None:
    result = sanitize(_valid_payload_dict())
    assert result.prs == 71


def test_sanitizer_rejects_source_code_key() -> None:
    payload = _valid_payload_dict()
    payload["source_code"] = "def foo(): pass"
    with pytest.raises(SanitizationError, match="source"):
        sanitize(payload)


def test_sanitizer_rejects_body_key() -> None:
    payload = _valid_payload_dict()
    payload["written_tests"] = [{"body": "assert True", "name": "t"}]
    with pytest.raises(SanitizationError, match="body"):
        sanitize(payload)


def test_sanitizer_rejects_docstring_key() -> None:
    payload = _valid_payload_dict()
    payload["docstring"] = "Raises: ValueError"
    with pytest.raises(SanitizationError, match="docstring"):
        sanitize(payload)


def test_sanitizer_rejects_overlong_string() -> None:
    payload = _valid_payload_dict()
    payload["project_alias"] = "x" * 501
    with pytest.raises(SanitizationError, match="501"):
        sanitize(payload)


def test_sanitizer_rejects_overlong_string_in_nested_list() -> None:
    payload = _valid_payload_dict()
    payload["written_tests"] = [{"reason": "x" * 501}]
    with pytest.raises(SanitizationError):
        sanitize(payload)


def test_sanitizer_rejects_code_key_in_nested_dict() -> None:
    payload = _valid_payload_dict()
    payload["extra"] = {"function_code": "def f(): pass"}
    with pytest.raises(SanitizationError, match="function_code"):
        sanitize(payload)


# ── payload builder ────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_report(tmp_path: Path) -> Path:
    report = {
        "summary": {"prs_score": 71, "gaps_found": 23, "verified_and_written": 8},
        "written": [
            {
                "test_function_name": "test_payment_rejects_zero_amount",
                "confidence_score": 94,
                "tier": "HIGH",
                "test_file_path": "tests/test_payments.py",
                "constraint_kind": "BOUNDARY",
                "spec_source": "pydantic",
            }
        ],
        "scaffolded": [
            {"stub_file": "tests/scaffold/test_refund.py", "reason": "external state", "age_days": 3}
        ],
        "flagged": [
            {"location": "src/billing.py:42", "reason": "external API", "constraint_kind": "MUST_RAISE"}
        ],
    }
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report))
    return p


def test_build_sync_payload_returns_payload(sample_report: Path, tmp_path: Path) -> None:
    payload = build_sync_payload(sample_report, project_root=tmp_path)
    assert payload is not None
    assert payload.prs == 71
    assert len(payload.written_tests) == 1
    assert payload.written_tests[0].name == "test_payment_rejects_zero_amount"
    assert len(payload.scaffolded_items) == 1
    assert len(payload.flagged_items) == 1


def test_build_sync_payload_missing_report(tmp_path: Path) -> None:
    result = build_sync_payload(tmp_path / "nonexistent.json", project_root=tmp_path)
    assert result is None


def test_build_sync_payload_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text("not valid json {{{{")
    result = build_sync_payload(p, project_root=tmp_path)
    assert result is None


def test_build_sync_payload_uses_alias(sample_report: Path, tmp_path: Path) -> None:
    payload = build_sync_payload(sample_report, project_root=tmp_path, project_alias="my-svc")
    assert payload is not None
    assert payload.project_alias == "my-svc"


def test_build_sync_payload_fallback_alias(sample_report: Path, tmp_path: Path) -> None:
    payload = build_sync_payload(sample_report, project_root=tmp_path)
    assert payload is not None
    # alias falls back to directory name
    assert payload.project_alias == tmp_path.name


# ── push_report ────────────────────────────────────────────────────────────────

def test_push_report_returns_false_without_httpx() -> None:
    import sys
    httpx_bak = sys.modules.pop("httpx", None)
    try:
        # We need a real payload; fake one
        import datetime

        from quell.sync.client import push_report
        real_payload = SyncPayload(
            project_id="x",
            project_alias="svc",
            run_at=datetime.datetime.now(datetime.UTC),
            quell_version="2.0.1",
            prs=0,
            prs_delta=0,
            edge_cases=EdgeCaseCounts(total=0, written=0, scaffolded=0, flagged=0),
        )
        result = push_report(real_payload, token="tok")
        assert not result.ok
    finally:
        if httpx_bak:
            sys.modules["httpx"] = httpx_bak


def test_push_report_handles_401() -> None:
    import datetime
    import sys
    mock_httpx = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_httpx.post.return_value = mock_resp

    real_payload = SyncPayload(
        project_id="x",
        project_alias="svc",
        run_at=datetime.datetime.now(datetime.UTC),
        quell_version="2.0.1",
        prs=0,
        prs_delta=0,
        edge_cases=EdgeCaseCounts(total=0, written=0, scaffolded=0, flagged=0),
    )

    with patch.dict(sys.modules, {"httpx": mock_httpx}):
        from importlib import reload

        import quell.sync.client as client_mod
        reload(client_mod)
        result = client_mod.push_report(real_payload, token="tok")
        assert not result.ok
        assert "auth error" in result.reason


def test_push_report_handles_429() -> None:
    import datetime
    import sys
    mock_httpx = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.headers = {"Retry-After": "30"}
    mock_httpx.post.return_value = mock_resp

    real_payload = SyncPayload(
        project_id="x",
        project_alias="svc",
        run_at=datetime.datetime.now(datetime.UTC),
        quell_version="2.0.1",
        prs=0,
        prs_delta=0,
        edge_cases=EdgeCaseCounts(total=0, written=0, scaffolded=0, flagged=0),
    )

    with patch.dict(sys.modules, {"httpx": mock_httpx}):
        from importlib import reload

        import quell.sync.client as client_mod
        reload(client_mod)
        result = client_mod.push_report(real_payload, token="tok")
        assert not result.ok
        assert "rate-limited" in result.reason
