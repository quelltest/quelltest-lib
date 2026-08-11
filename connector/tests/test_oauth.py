"""Tests for OAuth 2.0 PKCE endpoints (spec8 §11.5, issue #111)."""
from __future__ import annotations

import base64
import hashlib
import secrets

from fastapi.testclient import TestClient

from connector.main import app
from connector.oauth import pkce_code_challenge

client = TestClient(app, raise_server_exceptions=False)


def _make_verifier() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) pair."""
    verifier = secrets.token_urlsafe(64)
    challenge = pkce_code_challenge(verifier)
    return verifier, challenge


def test_pkce_challenge_is_s256() -> None:
    verifier = "abc123"
    challenge = pkce_code_challenge(verifier)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected


def test_oauth_authorize_redirects() -> None:
    _, challenge = _make_verifier()
    resp = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": "https://claude.ai/callback",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "quelltest.com" in resp.headers["location"]


def test_oauth_authorize_rejects_wrong_response_type() -> None:
    _, challenge = _make_verifier()
    resp = client.get(
        "/oauth/authorize",
        params={
            "response_type": "token",  # not supported
            "client_id": "test",
            "redirect_uri": "https://claude.ai/callback",
            "state": "s",
            "code_challenge": challenge,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_oauth_authorize_rejects_plain_challenge_method() -> None:
    _, challenge = _make_verifier()
    resp = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test",
            "redirect_uri": "https://claude.ai/callback",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "plain",  # not supported
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_well_known_metadata() -> None:
    resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    data = resp.json()
    assert "S256" in data["code_challenge_methods_supported"]
    assert "quell:reports:read" in data["scopes_supported"]
    assert "quell:reproduce:write" in data["scopes_supported"]


def test_health_endpoint() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_mcp_get_returns_sse() -> None:
    resp = client.get("/mcp")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
