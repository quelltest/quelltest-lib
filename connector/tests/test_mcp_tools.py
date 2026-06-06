"""Unit tests for all 8 MCP tools (spec8 §11.4, issue #112)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from connector.mcp_server import (
    _TOOL_REGISTRY,
    tool_get_badge_url,
    tool_get_flagged_items,
    tool_get_prs_history,
    tool_get_prs_report,
    tool_get_scaffolded_items,
    tool_get_written_tests,
    tool_list_projects,
    tool_reproduce_via_cloud,
)
from connector.models import TokenClaims

_READ_CLAIMS = TokenClaims(
    user_id="user1",
    email="user@test.com",
    tier="pro",
    scopes=["quell:reports:read"],
)

_FULL_CLAIMS = TokenClaims(
    user_id="user1",
    email="user@test.com",
    tier="pro",
    scopes=["quell:reports:read", "quell:reproduce:write"],
)

_SAMPLE_REPORT = {
    "project_id": "abc123",
    "project_alias": "payments-service",
    "prs": 71,
    "prs_delta": 12,
    "edge_cases": {"total": 23, "written": 8, "scaffolded": 3, "flagged": 2},
    "written_tests": [
        {"name": "test_payment_rejects_zero", "confidence": 94, "tier": "HIGH",
         "file": "tests/test_payments.py", "edge_case_type": "BOUNDARY", "spec_source": "pydantic"},
        {"name": "test_amount_negative", "confidence": 72, "tier": "MEDIUM",
         "file": "tests/test_payments.py", "edge_case_type": "BOUNDARY", "spec_source": "docstring"},
    ],
    "scaffolded_items": [
        {"stub_file": "tests/scaffold/test_refund.py", "reason": "external state", "age_days": 3}
    ],
    "flagged_items": [
        {"location": "src/billing.py:42", "reason": "external API: stripe.Charge.create()",
         "edge_case_type": "MUST_RAISE"}
    ],
}


def _mock_client(report=None, projects=None, history=None):
    """Return a patched DashboardClient."""
    client = AsyncMock()
    client.resolve_project_id.return_value = "abc123"
    client.list_projects.return_value = projects or [
        {"id": "abc123", "alias": "payments-service", "last_run": "2026-06-06T12:00:00Z",
         "prs": 71}
    ]
    client.get_latest_report.return_value = report or _SAMPLE_REPORT
    client.get_history.return_value = history or [
        {"run_at": "2026-06-06T12:00:00Z", "prs": 71, "delta": 12},
        {"run_at": "2026-06-01T09:00:00Z", "prs": 59, "delta": 8},
    ]
    client.reproduce_via_cloud.return_value = {
        "test_code": "def test_foo(): ...",
        "verified": True,
    }
    return client


# ── Tool 1: list_projects ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_projects_returns_list() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_list_projects({}, _READ_CLAIMS)
    assert "projects" in result
    assert result["projects"][0]["prs"] == 71
    assert result["projects"][0]["prs_tier"] == "Review Needed"


# ── Tool 2: get_prs_report ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_prs_report_returns_report() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_prs_report({"project_alias": "payments-service"}, _READ_CLAIMS)
    assert result["prs"] == 71


@pytest.mark.asyncio
async def test_get_prs_report_missing_alias() -> None:
    with pytest.raises(ValueError, match="project_alias"):
        await tool_get_prs_report({}, _READ_CLAIMS)


@pytest.mark.asyncio
async def test_get_prs_report_unknown_project() -> None:
    client = _mock_client()
    client.resolve_project_id.return_value = None
    with patch("connector.mcp_server._client", return_value=client):
        with pytest.raises(ValueError, match="not found"):
            await tool_get_prs_report({"project_alias": "unknown"}, _READ_CLAIMS)


# ── Tool 3: get_prs_history ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_prs_history_returns_history() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_prs_history(
            {"project_alias": "payments-service", "last_n_runs": 5}, _READ_CLAIMS
        )
    assert "history" in result
    assert len(result["history"]) == 2


# ── Tool 4: get_written_tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_written_tests_all() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_written_tests({"project_alias": "payments-service"}, _READ_CLAIMS)
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_get_written_tests_filter_medium() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_written_tests(
            {"project_alias": "payments-service", "tier": "MEDIUM"}, _READ_CLAIMS
        )
    assert result["total"] == 1
    assert result["written_tests"][0]["tier"] == "MEDIUM"


# ── Tool 5: get_flagged_items ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_flagged_items() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_flagged_items({"project_alias": "payments-service"}, _READ_CLAIMS)
    assert len(result["flagged_items"]) == 1
    assert "stripe" in result["flagged_items"][0]["reason"]


# ── Tool 6: get_scaffolded_items ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_scaffolded_items() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_scaffolded_items({"project_alias": "payments-service"}, _READ_CLAIMS)
    assert len(result["scaffolded_items"]) == 1
    assert result["scaffolded_items"][0]["age_days"] == 3


# ── Tool 7: get_badge_url ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_badge_url() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_get_badge_url({"project_alias": "payments-service"}, _READ_CLAIMS)
    assert "payments-service.svg" in result["badge_url"]
    assert "![Quell PRS]" in result["markdown"]
    assert result["prs"] == 71


# ── Tool 8: reproduce_via_cloud ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reproduce_via_cloud_requires_write_scope() -> None:
    with pytest.raises(PermissionError, match="quell:reproduce:write"):
        await tool_reproduce_via_cloud(
            {"project_alias": "svc", "bug_description": "bug"},
            _READ_CLAIMS,  # only has read scope
        )


@pytest.mark.asyncio
async def test_reproduce_via_cloud_with_full_scope() -> None:
    with patch("connector.mcp_server._client", return_value=_mock_client()):
        result = await tool_reproduce_via_cloud(
            {
                "project_alias": "payments-service",
                "bug_description": "payment accepts zero amount",
                "function_signature": "def process_payment(amount: float) -> dict:",
                "docstring": "Raises: ValueError if amount <= 0",
            },
            _FULL_CLAIMS,
        )
    assert result["verified"] is True


# ── Tool registry ──────────────────────────────────────────────────────────────

def test_all_8_tools_registered() -> None:
    expected = {
        "list_projects",
        "get_prs_report",
        "get_prs_history",
        "get_written_tests",
        "get_flagged_items",
        "get_scaffolded_items",
        "get_badge_url",
        "reproduce_via_cloud",
    }
    assert set(_TOOL_REGISTRY.keys()) == expected
