"""Bearer token validation middleware for the connector MCP server."""
from __future__ import annotations

import os
from typing import Any

from fastapi import Header, HTTPException, status

from connector.models import TokenClaims

_API_URL = os.environ.get("QUELLTEST_API_URL", "https://api.quelltest.com")


async def validate_token(authorization: str = Header(...)) -> TokenClaims:
    """Extract and validate Bearer token.

    Validates with api.quelltest.com/v1/auth/validate.
    Raises 401 if missing/invalid, 403 if wrong scopes.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
        )
    token = authorization[len("Bearer "):]

    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_API_URL}/v1/auth/validate",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Token validation failed")
        data = resp.json()
        return TokenClaims(**data)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Auth error: {exc}") from exc


def require_scope(scope: str) -> Any:
    """Dependency factory — raises 403 if the required scope is missing."""
    async def _check(claims: TokenClaims = ...) -> TokenClaims:  # type: ignore[assignment]
        if scope not in claims.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{scope}' required",
            )
        return claims
    return _check
