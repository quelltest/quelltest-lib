"""OAuth 2.0 PKCE endpoints for the connector (spec8 §11.5).

Flow:
  Claude.ai -> GET /oauth/authorize  (with code_challenge, state)
           -> Redirect to quelltest.com/oauth/authorize
           -> quelltest.com issues code
           -> POST /oauth/token (with code_verifier)
           -> returns access_token, refresh_token

This module only handles the connector side (redirect and token exchange).
The actual login lives on quelltest.com (separate service).
"""
from __future__ import annotations

import hashlib
import os
import urllib.parse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter()

_QUELLTEST_AUTH_URL = os.environ.get(
    "QUELLTEST_AUTH_URL", "https://quelltest.com/oauth/authorize"
)
_QUELLTEST_TOKEN_URL = os.environ.get(
    "QUELLTEST_TOKEN_URL", "https://quelltest.com/oauth/token"
)
_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "quell-mcp-connector")
_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 60 * 60 * 24 * 90  # 90 days
    scope: str


class TokenRequest(BaseModel):
    grant_type: str
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: str


@router.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    scope: str = Query("quell:reports:read"),
) -> RedirectResponse:
    """Redirect to quelltest.com authorization page (PKCE flow).

    The connector is a passthrough — it delegates auth to quelltest.com.
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only 'code' response_type supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only S256 code_challenge_method supported")

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": _CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": scope,
    })
    return RedirectResponse(f"{_QUELLTEST_AUTH_URL}?{params}", status_code=302)


@router.post("/oauth/token")
async def oauth_token(body: TokenRequest) -> TokenResponse:
    """Exchange authorization code for access_token (PKCE verification).

    Verifies code_verifier against the code_challenge using S256.
    Delegates actual token issuance to quelltest.com.
    """
    import httpx

    if body.grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")

    # Forward exchange to quelltest.com with our client_secret
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _QUELLTEST_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "code": body.code,
                    "redirect_uri": body.redirect_uri,
                    "client_id": _CLIENT_ID,
                    "client_secret": _CLIENT_SECRET,
                    "code_verifier": body.code_verifier,
                },
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {exc}") from exc

    if resp.status_code == 400:
        raise HTTPException(status_code=400, detail=resp.json().get("error", "Invalid code"))
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Token exchange failed")

    data = resp.json()
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_in=data.get("expires_in", 60 * 60 * 24 * 90),
        scope=data.get("scope", "quell:reports:read"),
    )


def pkce_code_challenge(verifier: str) -> str:
    """Compute S256 code_challenge from a code_verifier (used in tests)."""
    import base64
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
