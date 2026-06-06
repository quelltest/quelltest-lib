"""Quell Connector FastAPI app — mcp.quelltest.com (spec8 §11.6).

Routes:
  POST /mcp              MCP Streamable HTTP transport (2025-03-26)
  GET  /mcp              SSE fallback
  GET  /oauth/authorize  Redirect to quelltest.com auth
  POST /oauth/token      Token exchange (PKCE)
  GET  /.well-known/oauth-authorization-server
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from connector.mcp_server import router as mcp_router
from connector.oauth import router as oauth_router

app = FastAPI(
    title="Quell Connector",
    description=(
        "MCP server connecting Claude.ai to Quell production readiness reports. "
        "Your source code never leaves your machine."
    ),
    version="2.0.1",
    docs_url="/docs" if os.environ.get("ENVIRONMENT") != "production" else None,
)

app.include_router(mcp_router)
app.include_router(oauth_router)


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> dict:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    base = os.environ.get("CONNECTOR_URL", "https://mcp.quelltest.com")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["quell:reports:read", "quell:reproduce:write"],
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "quell-connector"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
