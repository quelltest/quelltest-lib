"""
Quell GitHub App — webhook server deployed at your chosen host.

Receives GitHub pull_request events, runs the Quell guard-clause scanner on
the changed Python files (via GitHub API — no repo clone needed), and posts
a verified comment back to the PR.

Environment variables required:
    GITHUB_APP_ID          — App ID from GitHub App settings
    GITHUB_APP_PRIVATE_KEY — PEM private key (paste full contents, \\n escaped)
    GITHUB_WEBHOOK_SECRET  — Webhook secret set in App settings
    QUELL_WORK_DIR         — (optional) temp dir for file writes (default: /tmp)

Run locally:
    pip install quelltest fastapi uvicorn PyJWT cryptography
    uvicorn quell.github.app:app --host 0.0.0.0 --port 8080

Architecture:
    GitHub sends pull_request webhook
        → validate HMAC signature
        → get installation token (no repo clone — uses GitHub API directly)
        → GitHubPRRunner fetches changed .py files via Contents API
        → CodeGuardReader scans for untested guard clauses
        → format results as markdown
        → post/update PR comment
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response

from quell.github.auth import generate_app_jwt, get_installation_token
from quell.github.pr_commenter import post_or_update_pr_comment

app = FastAPI(title="Quell GitHub App", version="1.0.0")

_APP_ID = os.getenv("GITHUB_APP_ID", "")
_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").encode()


@app.get("/")
def health() -> dict:
    """Health check for Render / uptime monitors."""
    return {"status": "ok", "service": "quell-github-app"}


@app.post("/github/webhook")
async def github_webhook(request: Request) -> Response:
    """
    Handle incoming GitHub webhook events.

    Only processes pull_request events with action opened/synchronize/reopened.
    All other events return 200 immediately.
    """
    body = await request.body()
    _verify_signature(body, request.headers.get("X-Hub-Signature-256", ""))

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return Response(content="ignored", status_code=200)

    payload = json.loads(body)
    action = payload.get("action", "")
    if action not in {"opened", "synchronize", "reopened"}:
        return Response(content="ignored", status_code=200)

    # Fire-and-forget so GitHub doesn't time out the webhook
    asyncio.create_task(_handle_pr_event(payload))
    return Response(content="accepted", status_code=202)


def _verify_signature(body: bytes, signature_header: str) -> None:
    """Validate the HMAC-SHA256 webhook signature from GitHub."""
    if not _WEBHOOK_SECRET:
        return  # skip validation if not configured (dev mode)
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing signature")
    expected = "sha256=" + hmac.new(_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=403, detail="Invalid signature")


async def _handle_pr_event(payload: dict) -> None:
    """
    Fetch changed files via GitHub API, run CodeGuardReader, post PR comment.

    Uses the Contents API — no repo clone needed. Runs in a background task
    so the webhook response returns immediately.
    """
    repo_full = payload["repository"]["full_name"]   # "owner/repo"
    pr_number = payload["pull_request"]["number"]
    installation_id = payload["installation"]["id"]

    # Get installation token scoped to this repo
    app_jwt = generate_app_jwt(_APP_ID, _PRIVATE_KEY)
    token = await get_installation_token(app_jwt, installation_id)

    # Run guard-clause scan via GitHub API (no clone)
    from quell.github.pr_runner import GitHubPRRunner

    runner = GitHubPRRunner(
        pr_number=pr_number,
        repo=repo_full,
        token=token,
        project_root=Path("."),
    )

    try:
        report = runner.run_quell_on_pr()
    except Exception:
        return  # silently skip — avoid spam on broken repos

    comment_body = _format_app_comment(report)
    await post_or_update_pr_comment(token, repo_full, pr_number, comment_body)


# Marker so the bot updates its own comment instead of posting new ones
_COMMENT_MARKER = "<!-- quell-guard-scan -->"


def _format_app_comment(report: dict) -> str:
    """Format the guard-clause scan results as GitHub PR markdown."""
    from quell import __version__

    gaps = report.get("gaps", [])
    total = report.get("total_requirements", 0)
    covered = report.get("covered_requirements", 0)

    emoji = "\U0001f7e2" if not gaps else ("\U0001f7e1" if len(gaps) < 5 else "\U0001f534")
    lines = [_COMMENT_MARKER, ""]
    lines.append(f"## {emoji} Quell — Guard Clause Scan")
    lines.append("")

    if total == 0:
        lines.append("No guard clauses found in changed Python files.")
    elif not gaps:
        lines.append(f"✅ **All {total} guard clause{'s' if total != 1 else ''} are tested.**")
    else:
        pct = int(covered / total * 100) if total else 100
        lines.append(
            f"**{len(gaps)} untested guard clause{'s' if len(gaps) != 1 else ''} found** "
            f"in changed files &nbsp;|&nbsp; {pct}% covered ({covered}/{total})"
        )
        lines.append("")
        lines.append("| File | Function | Guard | Type |")
        lines.append("|------|----------|-------|------|")
        for g in gaps[:15]:
            guard_text = (g.get("description") or "")[:60]
            line_ref = f":{g['line']}" if g.get("line") else ""
            lines.append(
                f"| `{g['file']}{line_ref}` | `{g['function']}` "
                f"| {guard_text} | `{g['kind']}` |"
            )
        if len(gaps) > 15:
            lines.append(f"| _...and {len(gaps) - 15} more_ | | | |")
        lines.append("")
        lines.append("**Fix locally:** `quell scan src/ --fix`")

    lines.append("")
    lines.append("---")
    lines.append(
        f"*[Quell](https://quell.buildsbyshashank.tech) v{__version__} "
        "— rule-based guard scanner, no code sent to any server*"
    )
    return "\n".join(lines)


def main() -> None:
    """Entry point for `quell-github-app` CLI command."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()
