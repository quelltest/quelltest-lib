"""
OAuth 2.0 PKCE flow for Quell CLI.

Flow:
1. Generate PKCE code_verifier + code_challenge
2. Start local HTTP server on localhost:7642
3. Open browser to quell.buildsbyshashank.tech/auth/login
4. Browser redirects back to localhost:7642/callback?code=...&state=...
5. Exchange auth_code for access_token + refresh_token
6. Save tokens to ~/.quell/credentials.json (chmod 600)
7. Server records session_id — single concurrent session enforced

Single-session enforcement (server-side):
- Each access_token contains a session_id
- Server stores: user_id → active_session_id
- New login → new session_id → old tokens become invalid
- Two simultaneous requests with same token → server detects,
  revokes token, requires re-login
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

QUELL_API_BASE = "https://quell.buildsbyshashank.tech/api"
QUELL_AUTH_BASE = "https://quell.buildsbyshashank.tech/auth"
CREDENTIALS_PATH = Path.home() / ".quell" / "credentials.json"
CALLBACK_PORT = 7642
CLIENT_ID = "quell-cli"  # public client — no client_secret for PKCE


def _pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def login() -> dict:  # type: ignore[type-arg]
    """
    Full OAuth PKCE browser login flow.

    Returns credentials dict on success.
    Raises RuntimeError on failure or timeout.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}/callback",
        "response_type": "code",
        "scope": "quell:read quell:write",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{QUELL_AUTH_BASE}/login?" + urlencode(params)

    result: dict = {}  # type: ignore[type-arg]
    error: list[str] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            returned_state = qs.get("state", [None])[0]
            err = qs.get("error", [None])[0]

            if err:
                error.append(err)
                self._respond("Authentication failed. You can close this tab.")
                return

            if returned_state != state:
                error.append("State mismatch — possible CSRF attack")
                self._respond("Authentication failed. You can close this tab.")
                return

            if code:
                result["code"] = code
                self._respond(
                    "&#10003; Quell authenticated successfully! "
                    "You can close this tab and return to your terminal."
                )

        def _respond(self, message: str) -> None:
            html = (
                f"<!DOCTYPE html><html><body "
                f'style="font-family:sans-serif;padding:40px;text-align:center">'
                f"<h2>{message}</h2></body></html>"
            )
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            # Force browser to close the connection so server.shutdown() doesn't hang
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def log_message(self, *args: object) -> None:
            pass  # suppress server logs

    server = HTTPServer(("localhost", CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    print("\nOpening browser for login...")
    print(f"If browser doesn't open: {auth_url}\n")
    webbrowser.open(auth_url)

    deadline = time.time() + 120
    while time.time() < deadline:
        if result.get("code") or error:
            break
        time.sleep(0.5)
    server.shutdown()

    if error:
        raise RuntimeError(f"Authentication failed: {error[0]}")
    if not result.get("code"):
        raise RuntimeError("Authentication timed out. Please try again.")

    token_resp = httpx.post(
        f"{QUELL_AUTH_BASE}/token",
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": f"http://localhost:{CALLBACK_PORT}/callback",
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        },
        timeout=8.0,
    )
    if token_resp.status_code >= 400:
        detail = token_resp.json().get("detail", token_resp.text) if token_resp.headers.get("content-type", "").startswith("application/json") else token_resp.text
        raise RuntimeError(f"Token exchange failed ({token_resp.status_code}): {detail}")
    token_resp.raise_for_status()
    tokens = token_resp.json()

    credentials = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + tokens.get("expires_in", 3600),
        "email": tokens.get("email", ""),
        "plan": tokens.get("plan", "free"),
        "session_id": tokens.get("session_id", ""),
    }
    _save_credentials(credentials)
    return credentials


def logout() -> None:
    """Revoke token on server and delete local credentials."""
    creds = load_credentials()
    if creds and creds.get("access_token"):
        try:
            httpx.post(
                f"{QUELL_AUTH_BASE}/logout",
                headers={"Authorization": f"Bearer {creds['access_token']}"},
                timeout=5.0,
            )
        except Exception:
            pass  # best effort — always delete local creds
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


def load_credentials() -> dict | None:  # type: ignore[type-arg]
    """Load saved credentials. Returns None if not logged in."""
    env_token = os.environ.get("QUELL_API_KEY")
    if env_token:
        return {"access_token": env_token, "email": "ci", "plan": "ci"}

    if not CREDENTIALS_PATH.exists():
        return None
    try:
        return json.loads(CREDENTIALS_PATH.read_text())  # type: ignore[no-any-return]
    except Exception:
        return None


def get_valid_token() -> str | None:
    """
    Return a valid access token, refreshing if expired.
    Returns None if not logged in.
    """
    creds = load_credentials()
    if not creds:
        return None

    expires_at = creds.get("expires_at", 0)
    if expires_at and time.time() > expires_at - 60:
        refreshed = _refresh_token(creds.get("refresh_token"))
        if refreshed:
            return refreshed.get("access_token")
        return None

    return creds.get("access_token")


def verify_token(token: str) -> dict:  # type: ignore[type-arg]
    """
    Verify token with server. Returns user info or raises.

    Server enforces single-session: if this token's session_id
    doesn't match the current active session, returns 401.
    """
    r = httpx.get(
        f"{QUELL_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )
    if r.status_code == 401:
        raise RuntimeError(
            "Session expired or used from another device. "
            "Run: quell auth login"
        )
    r.raise_for_status()
    return r.json()  # type: ignore[no-any-return]


def _refresh_token(refresh_token: str | None) -> dict | None:  # type: ignore[type-arg]
    if not refresh_token:
        return None
    try:
        r = httpx.post(
            f"{QUELL_AUTH_BASE}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            tokens = r.json()
            creds = load_credentials() or {}
            creds.update({
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token", refresh_token),
                "expires_at": time.time() + tokens.get("expires_in", 3600),
            })
            _save_credentials(creds)
            return creds
    except Exception:
        pass
    return None


def _save_credentials(credentials: dict) -> None:  # type: ignore[type-arg]
    """Save credentials to ~/.quell/credentials.json with chmod 600."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(credentials, indent=2))
    CREDENTIALS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # owner read/write only
