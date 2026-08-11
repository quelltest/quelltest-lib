"""HTTP client for api.quelltest.com — used by MCP tools to read synced data."""
from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = os.environ.get("QUELLTEST_API_URL", "https://api.quelltest.com")
_TIMEOUT = 10.0


class DashboardClient:
    """Thin async HTTP client wrapping the dashboard API."""

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def list_projects(self) -> list[dict[str, Any]]:
        """GET /v1/projects — list all synced projects for this user."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE}/v1/projects", headers=self._headers)
            resp.raise_for_status()
            return resp.json().get("projects", [])

    async def get_latest_report(self, project_id: str) -> dict[str, Any]:
        """GET /v1/projects/:id/reports/latest."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/v1/projects/{project_id}/reports/latest",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_history(self, project_id: str, last_n: int = 10) -> list[dict[str, Any]]:
        """GET /v1/projects/:id/history?last_n=N."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/v1/projects/{project_id}/history",
                params={"last_n": last_n},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json().get("history", [])

    async def resolve_project_id(self, alias: str) -> str | None:
        """Resolve a human alias to a project_id."""
        projects = await self.list_projects()
        for p in projects:
            if p.get("alias") == alias or p.get("id") == alias:
                return p["id"]
        return None

    async def delete_project(self, project_id: str) -> bool:
        """DELETE /v1/projects/:id — unlink project, delete all remote data."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{_BASE}/v1/projects/{project_id}",
                headers=self._headers,
            )
            return resp.status_code in (200, 204)

    async def reproduce_via_cloud(
        self,
        project_alias: str,
        bug_description: str,
        function_signature: str,
        docstring: str,
    ) -> dict[str, Any]:
        """POST /v1/reproduce — cloud reproduce endpoint (Pro/Team)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_BASE}/v1/reproduce",
                json={
                    "project_alias": project_alias,
                    "bug_description": bug_description,
                    "function_signature": function_signature,
                    "docstring": docstring,
                },
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()
