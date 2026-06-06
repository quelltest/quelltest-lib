"""HTTP client for pushing sync payloads to api.quelltest.com.

All error paths warn and return PushResult(ok=False) — never raise.
A failed sync must never interrupt a `quell find` run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from quell.sync.models import SyncPayload
from quell.sync.payload import record_push

_API_URL = "https://api.quelltest.com/v1/sync"
_TIMEOUT = 10.0


@dataclass
class PushResult:
    ok: bool
    reason: str = ""
    dashboard_url: str = ""


def _load_token() -> str | None:
    """Load Bearer token from ~/.config/quell/auth.json."""
    import os
    config_dir = (
        Path(os.environ.get("APPDATA", "")) / "quell"
        if os.name == "nt"
        else Path.home() / ".config" / "quell"
    )
    auth_file = config_dir / "auth.json"
    try:
        if auth_file.exists():
            data = json.loads(auth_file.read_text())
            return data.get("access_token") or data.get("key_encrypted")
    except Exception:  # noqa: BLE001
        pass
    return None


def push_report(payload: SyncPayload, token: str | None = None) -> PushResult:
    """POST the sanitized payload to api.quelltest.com/v1/sync.

    Bearer token is sourced from ~/.config/quell/auth.json if not provided.
    All error conditions warn and return ok=False — never raise.
    """
    try:
        import httpx
    except ImportError:
        return PushResult(ok=False, reason="httpx not installed (pip install httpx)")

    bearer = token or _load_token()
    if not bearer:
        return PushResult(
            ok=False,
            reason="No auth token found. Run `quell auth login` first.",
        )

    try:
        body = payload.model_dump(mode="json")
        # Convert datetime to ISO string for JSON serialisation
        body["run_at"] = payload.run_at.isoformat()

        response = httpx.post(
            _API_URL,
            json=body,
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )

        if response.status_code == 201:
            record_push(payload)
            url = f"https://quelltest.com/dashboard/{payload.project_alias}"
            return PushResult(ok=True, dashboard_url=url)

        if response.status_code in (401, 403):
            return PushResult(
                ok=False,
                reason="Sync failed: auth error. Run `quell auth login`.",
            )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            return PushResult(
                ok=False,
                reason=f"Sync rate-limited. Retry in {retry_after} seconds.",
            )

        return PushResult(
            ok=False,
            reason=f"Sync failed: server returned {response.status_code}. Report saved locally.",
        )

    except Exception as exc:  # noqa: BLE001
        return PushResult(
            ok=False,
            reason=f"Sync failed: {exc}. Report saved locally.",
        )
