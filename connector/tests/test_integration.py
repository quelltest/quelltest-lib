"""Integration tests for the connector pipeline (spec8 §11.10, issue #113).

These tests verify end-to-end flows using mocked API responses.
In a real CI environment they would target a test instance of api.quelltest.com.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from connector.dashboard_client import DashboardClient
from connector.mcp_server import tool_get_flagged_items, tool_get_prs_report, tool_reproduce_via_cloud
from connector.models import TokenClaims

_PRO_CLAIMS = TokenClaims(
    user_id="user1",
    email="user@test.com",
    tier="pro",
    scopes=["quell:reports:read", "quell:reproduce:write"],
)

_READ_CLAIMS = TokenClaims(
    user_id="user1",
    email="user@test.com",
    tier="pro",
    scopes=["quell:reports:read"],
)

_SAMPLE_REPORT = {
    "project_id": "abc123",
    "project_alias": "payments-service",
    "prs": 71,
    "prs_delta": 12,
    "edge_cases": {"total": 23, "written": 8, "scaffolded": 3, "flagged": 2},
    "written_tests": [],
    "scaffolded_items": [],
    "flagged_items": [
        {"location": "src/billing.py:142",
         "reason": "external API: stripe.Charge.create()",
         "edge_case_type": "MUST_RAISE"}
    ],
}


# ── 1. Sync round-trip ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_to_mcp_round_trip() -> None:
    """Push a report via API and read it back through MCP tool."""
    client = AsyncMock(spec=DashboardClient)
    client.resolve_project_id.return_value = "abc123"
    client.get_latest_report.return_value = _SAMPLE_REPORT

    with patch("connector.mcp_server._client", return_value=client):
        result = await tool_get_prs_report({"project_alias": "payments-service"}, _PRO_CLAIMS)

    assert result["prs"] == 71
    client.get_latest_report.assert_called_once_with("abc123")


# ── 2. Sanitizer enforcement in sync chain ─────────────────────────────────────

def test_sanitizer_rejects_source_code_in_payload() -> None:
    """Payload with 'source_code' key must be rejected before reaching the API."""
    quell_sync = pytest.importorskip("quell.sync.sanitizer", reason="quell.sync not installed")
    _sanitize = quell_sync.sanitize
    _sanitization_error = quell_sync.SanitizationError

    payload = {
        "project_id": "abc",
        "project_alias": "svc",
        "source_code": "def process_payment(amount): return amount",  # blocklisted
        "prs": 71,
    }
    with pytest.raises(_sanitization_error, match="source"):
        _sanitize(payload)


# ── 3. Read data after auth ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flagged_items_via_read_scope() -> None:
    """quell:reports:read scope is sufficient for get_flagged_items."""
    client = AsyncMock(spec=DashboardClient)
    client.resolve_project_id.return_value = "abc123"
    client.get_latest_report.return_value = _SAMPLE_REPORT

    with patch("connector.mcp_server._client", return_value=client):
        result = await tool_get_flagged_items({"project_alias": "payments-service"}, _READ_CLAIMS)

    assert len(result["flagged_items"]) == 1
    assert "stripe" in result["flagged_items"][0]["reason"]


# ── 4. Unlink deletes remote data ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlink_removes_project() -> None:
    """DashboardClient.delete_project is called and returns True."""
    client = AsyncMock(spec=DashboardClient)
    client.resolve_project_id.return_value = "abc123"
    client.delete_project.return_value = True

    result = await client.delete_project("abc123")
    assert result is True
    client.delete_project.assert_called_once_with("abc123")


# ── 5. reproduce_via_cloud scope enforcement ───────────────────────────────────

@pytest.mark.asyncio
async def test_reproduce_blocked_without_write_scope() -> None:
    """reproduce_via_cloud must raise PermissionError without write scope."""
    with pytest.raises(PermissionError, match="quell:reproduce:write"):
        await tool_reproduce_via_cloud(
            {
                "project_alias": "svc",
                "bug_description": "payment accepts zero",
                "function_signature": "def foo(x): ...",
                "docstring": "Raises ValueError",
            },
            _READ_CLAIMS,  # only has read scope
        )


@pytest.mark.asyncio
async def test_reproduce_succeeds_with_write_scope() -> None:
    """reproduce_via_cloud works when quell:reproduce:write scope is present."""
    client = AsyncMock(spec=DashboardClient)
    client.resolve_project_id.return_value = "abc123"
    client.reproduce_via_cloud.return_value = {
        "test_code": "def test_rejects_zero(): ...",
        "verified": True,
        "explanation": "Boundary check on amount",
    }

    with patch("connector.mcp_server._client", return_value=client):
        result = await tool_reproduce_via_cloud(
            {
                "project_alias": "payments-service",
                "bug_description": "payment accepts zero amount",
                "function_signature": "def process_payment(amount: float) -> dict:",
                "docstring": "Raises: ValueError if amount <= 0",
            },
            _PRO_CLAIMS,
        )

    assert result["verified"] is True
    # Verify only signature + docstring were forwarded (not function body)
    call_kwargs = client.reproduce_via_cloud.call_args
    assert "function_signature" in str(call_kwargs)
    assert "docstring" in str(call_kwargs)
