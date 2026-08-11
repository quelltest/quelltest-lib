"""MCP Streamable HTTP server — all 8 Quell connector tools (spec8 §11.4).

Implements the MCP 2025-03-26 Streamable HTTP transport.
Tools read from api.quelltest.com via DashboardClient — never from local disk.

Rate limits (spec8 §11.6):
  list_projects, get_prs_report, get_prs_history,
  get_written_tests, get_flagged_items, get_scaffolded_items: 100 req/min
  get_badge_url: 500 req/min
  reproduce_via_cloud: 10 req/min
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from connector.dashboard_client import DashboardClient
from connector.middleware.auth import TokenClaims, validate_token
from connector.middleware.rate_limit import rate_limit

router = APIRouter()

_BADGE_BASE = "https://quell.buildsbyshashank.tech/badge"


def _prs_tier(prs: int) -> str:
    if prs >= 80:
        return "Production Ready"
    if prs >= 60:
        return "Review Needed"
    return "Edge Cases Uncovered"


def _client(claims: TokenClaims) -> DashboardClient:
    return DashboardClient(token=claims.user_id)  # user_id doubles as token in stub


# ── MCP Tool dispatcher ────────────────────────────────────────────────────────

_TOOL_REGISTRY: dict[str, Any] = {}


def _tool(name: str) -> Any:
    def decorator(fn: Any) -> Any:
        _TOOL_REGISTRY[name] = fn
        return fn
    return decorator


@_tool("list_projects")
async def tool_list_projects(params: dict, claims: TokenClaims) -> dict:
    """List all synced Quell projects for the authenticated user."""
    client = _client(claims)
    projects = await client.list_projects()
    return {
        "projects": [
            {
                "id": p.get("id"),
                "alias": p.get("alias"),
                "last_run": p.get("last_run"),
                "prs": p.get("prs", 0),
                "prs_tier": _prs_tier(p.get("prs", 0)),
            }
            for p in projects
        ]
    }


@_tool("get_prs_report")
async def tool_get_prs_report(params: dict, claims: TokenClaims) -> dict:
    """Get the latest PRS report for a project."""
    alias = params.get("project_alias", "")
    if not alias:
        raise ValueError("project_alias is required")
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    return await client.get_latest_report(pid)


@_tool("get_prs_history")
async def tool_get_prs_history(params: dict, claims: TokenClaims) -> dict:
    """Get PRS trend over time (last N runs)."""
    alias = params.get("project_alias", "")
    last_n = int(params.get("last_n_runs", 10))
    if not alias:
        raise ValueError("project_alias is required")
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    history = await client.get_history(pid, last_n=last_n)
    return {"history": history}


@_tool("get_written_tests")
async def tool_get_written_tests(params: dict, claims: TokenClaims) -> dict:
    """Get WRITTEN test metadata, optionally filtered by tier."""
    alias = params.get("project_alias", "")
    tier_filter = params.get("tier")  # HIGH / MEDIUM / LOW / None = all
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    report = await client.get_latest_report(pid)
    tests = report.get("written_tests", [])
    if tier_filter:
        tests = [t for t in tests if t.get("tier", "").upper() == tier_filter.upper()]
    return {"written_tests": tests, "total": len(tests)}


@_tool("get_flagged_items")
async def tool_get_flagged_items(params: dict, claims: TokenClaims) -> dict:
    """Get all FLAGGED items with reasons and locations."""
    alias = params.get("project_alias", "")
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    report = await client.get_latest_report(pid)
    return {"flagged_items": report.get("flagged_items", [])}


@_tool("get_scaffolded_items")
async def tool_get_scaffolded_items(params: dict, claims: TokenClaims) -> dict:
    """Get all SCAFFOLDED stubs including age (for PRS penalty tracking)."""
    alias = params.get("project_alias", "")
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    report = await client.get_latest_report(pid)
    return {"scaffolded_items": report.get("scaffolded_items", [])}


@_tool("get_badge_url")
async def tool_get_badge_url(params: dict, claims: TokenClaims) -> dict:
    """Get the SVG badge URL for a project's current PRS."""
    alias = params.get("project_alias", "")
    client = _client(claims)
    pid = await client.resolve_project_id(alias)
    if not pid:
        raise ValueError(f"Project '{alias}' not found")
    report = await client.get_latest_report(pid)
    prs = report.get("prs", 0)
    badge_url = f"{_BADGE_BASE}/{alias}.svg"
    return {
        "badge_url": badge_url,
        "markdown": f"![Quell PRS]({badge_url})",
        "prs": prs,
        "tier": _prs_tier(prs),
    }


@_tool("reproduce_via_cloud")
async def tool_reproduce_via_cloud(params: dict, claims: TokenClaims) -> dict:
    """Trigger quell reproduce via the cloud API (Pro/Team only).

    Sends only function_signature and docstring — never the function body.
    The generated test still runs all 5 gates server-side.
    Requires scope: quell:reproduce:write
    """
    if "quell:reproduce:write" not in claims.scopes:
        raise PermissionError("Scope 'quell:reproduce:write' required for reproduce_via_cloud")
    client = _client(claims)
    return await client.reproduce_via_cloud(
        project_alias=params.get("project_alias", ""),
        bug_description=params.get("bug_description", ""),
        function_signature=params.get("function_signature", ""),
        docstring=params.get("docstring", ""),
    )


# ── MCP HTTP transport ─────────────────────────────────────────────────────────

@router.post("/mcp")
async def mcp_post(
    request: Request,
    claims: TokenClaims = Depends(validate_token),
) -> StreamingResponse:
    """MCP Streamable HTTP transport (2025-03-26 spec).

    Accepts JSON-RPC 2.0 requests, dispatches to tool handlers,
    returns JSON-RPC 2.0 responses via SSE stream.
    """
    await rate_limit(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _error_response(None, -32700, "Parse error")

    method = body.get("method", "")
    rpc_id = body.get("id")
    params = body.get("params", {})

    if method == "tools/list":
        return _json_response(rpc_id, {
            "tools": [
                {"name": name, "description": fn.__doc__ or ""}
                for name, fn in _TOOL_REGISTRY.items()
            ]
        })

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})

        # Per-tool rate limiting
        if tool_name == "get_badge_url":
            await rate_limit(request, limit=500)
        elif tool_name == "reproduce_via_cloud":
            await rate_limit(request, limit=10)
        else:
            await rate_limit(request, limit=100)

        handler = _TOOL_REGISTRY.get(tool_name)
        if not handler:
            return _error_response(rpc_id, -32601, f"Unknown tool: {tool_name}")

        try:
            result = await handler(tool_params, claims)
            return _json_response(rpc_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
        except PermissionError as exc:
            return _error_response(rpc_id, -32000, str(exc))
        except ValueError as exc:
            return _error_response(rpc_id, -32602, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(rpc_id, -32000, f"Tool error: {exc}")

    return _error_response(rpc_id, -32601, f"Method not found: {method}")


@router.get("/mcp")
async def mcp_get(request: Request) -> StreamingResponse:
    """SSE fallback for older MCP clients."""
    async def _stream() -> Any:
        yield "data: {\"type\": \"connected\", \"server\": \"quell-connector\"}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _json_response(rpc_id: Any, result: Any) -> StreamingResponse:
    body = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    async def _stream() -> Any:
        yield f"data: {body}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _error_response(rpc_id: Any, code: int, message: str) -> StreamingResponse:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    })

    async def _stream() -> Any:
        yield f"data: {body}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream", status_code=400)
