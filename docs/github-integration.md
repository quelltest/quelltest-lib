# Quell — GitHub Integration Guide

Quell can review every pull request automatically and report untested guard
clauses as inline diff annotations and PR comments. There are two ways to set
this up — pick the one that fits your workflow.

---

## Option 1 — GitHub Actions (recommended for most teams)

No server needed. Runs inside your existing CI pipeline. Free for public repos.

### 1.1 Quickest setup — one command

Inside your repo, run:

```bash
quell install --pr
```

This writes `.github/workflows/quell.yml` and commits it. Done. Every future
PR triggers the scanner automatically.

### 1.2 Manual setup — add the workflow file yourself

Create `.github/workflows/quell.yml`:

```yaml
name: Quell — Guard Clause Scan

on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - "**.py"

permissions:
  contents: read
  pull-requests: write   # needed to post the PR comment

jobs:
  quell:
    name: Guard clause scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Scan for untested guard clauses
        uses: shashank7109/quelltest_lib@main
        with:
          target: '.'
          post-comment: 'true'
          fail-on-gaps: 'false'
```

Commit and push. Quell will scan every PR from now on.

### 1.3 Action inputs

| Input | Default | Description |
|-------|---------|-------------|
| `target` | `.` | File or directory to scan (relative to repo root). Use `src/` if your code lives there. |
| `python-version` | `3.11` | Python version used to run Quell. |
| `post-comment` | `true` | Post/update a PR comment with the gap table. Requires `pull-requests: write`. |
| `fail-on-gaps` | `false` | Exit 1 if any untested guard clauses are found. Blocks merge when `true`. |
| `github-token` | `${{ github.token }}` | Token for posting comments. The default works unless you need cross-repo access. |

### 1.4 Action outputs

You can use these in later steps:

```yaml
- name: Scan
  id: quell
  uses: shashank7109/quelltest_lib@main

- name: Show result
  run: echo "Found ${{ steps.quell.outputs.gaps-found }} gaps"
```

| Output | Description |
|--------|-------------|
| `gaps-found` | Number of untested guard clauses found |
| `total-guards` | Total guard clauses detected in changed files |
| `report-path` | Always `quell-report.json` — upload as artifact if needed |

### 1.5 Recipes

**Block merges when gaps exist:**

```yaml
- uses: shashank7109/quelltest_lib@main
  with:
    fail-on-gaps: 'true'
```

**Scan only the `src/` directory:**

```yaml
- uses: shashank7109/quelltest_lib@main
  with:
    target: 'src/'
```

**Upload the JSON report as a CI artifact:**

```yaml
- uses: shashank7109/quelltest_lib@main
  id: quell

- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: quell-report
    path: quell-report.json
```

**Run only on specific paths:**

```yaml
on:
  pull_request:
    paths:
      - "src/**/*.py"
      - "lib/**/*.py"
```

### 1.6 What you see in the PR

**Inline diff annotations** — each untested guard clause appears as a warning
directly in the diff view where the guard clause is written:

```
⚠  Untested guard [boundary] in process_payment()
   if amount <= 0:
```

**PR comment** — a summary table is posted (and updated on each push, not
re-posted):

```
🟡 Quell — Guard Clause Scan

3 untested guard clauses found — 60% covered (3/5)

| File           | Function         | Guard                    | Type     |
|----------------|------------------|--------------------------|----------|
| payments.py:32 | process_payment  | if amount <= 0:          | boundary |
| sessions.py:18 | create_session   | if not user:             | not_null |
| auth.py:44     | require_auth     | if not is_authenticated: | auth     |

Fix locally: quell scan . --fix
```

**No code is sent anywhere.** The scanner runs on the GitHub Actions runner
inside your own infrastructure. It is purely AST-based — no LLM, no API key.

---

## Option 2 — GitHub App (zero-config for your whole organisation)

Install once at the organisation level and every repo gets automatic PR
reviews without touching any workflow file.

### 2.1 Create the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   (or your org settings for an org-level app).

2. Fill in:
   - **App name**: `Quell` (or `quell-yourorg`)
   - **Homepage URL**: `https://quell.buildsbyshashank.tech` (or your own domain)
   - **Webhook URL**: `https://<your-server>/github/webhook` (see §2.3 for hosting)
   - **Webhook secret**: generate a random string, save it — you'll need it later

3. Under **Repository permissions**, set:
   - **Contents**: Read-only (to fetch file contents via API)
   - **Pull requests**: Read & write (to post comments)

4. Under **Subscribe to events**, tick **Pull request**.

5. Click **Create GitHub App**.

6. On the app page, note the **App ID** (a number like `123456`).

7. Scroll to **Private keys** → **Generate a private key** → download the `.pem` file.

### 2.2 Configure environment variables

You need these four values wherever you host the server:

| Variable | Where to get it |
|----------|-----------------|
| `GITHUB_APP_ID` | The number shown on the App settings page |
| `GITHUB_APP_PRIVATE_KEY` | Full contents of the `.pem` file (replace real newlines with `\n`) |
| `GITHUB_WEBHOOK_SECRET` | The secret you entered in step 2 above |
| `PORT` | Port to listen on (default `8080`) |

**Formatting the private key** — the PEM file has real newlines. Most hosting
platforms want the value as a single line with `\n` literals. On Linux/Mac:

```bash
cat your-app.pem | awk 'NF {printf "%s\\n", $0}' | pbcopy
```

On Windows PowerShell:

```powershell
(Get-Content your-app.pem -Raw).Replace("`r`n", "\n").Replace("`n", "\n") | Set-Clipboard
```

Paste the result as the value of `GITHUB_APP_PRIVATE_KEY`.

### 2.3 Deploy the server

The webhook server is at `quell/github/app.py`. It is a standard FastAPI app.

**Render (free tier):**

1. Fork or push `quelltest_lib` to your GitHub account.
2. Go to [render.com](https://render.com) → New → Web Service → connect your repo.
3. Set:
   - **Build command**: `pip install quelltest fastapi uvicorn PyJWT cryptography`
   - **Start command**: `uvicorn quell.github.app:app --host 0.0.0.0 --port $PORT`
4. Add the four environment variables under **Environment**.
5. Deploy. Copy the `https://your-app.onrender.com` URL.

**Railway:**

```bash
railway init
railway add
railway up
railway variables set GITHUB_APP_ID=... GITHUB_APP_PRIVATE_KEY=... GITHUB_WEBHOOK_SECRET=...
```

**Fly.io:**

```bash
fly launch --name quell-app --region iad
fly secrets set GITHUB_APP_ID=... GITHUB_APP_PRIVATE_KEY=... GITHUB_WEBHOOK_SECRET=...
fly deploy
```

**Docker (self-hosted):**

```dockerfile
FROM python:3.11-slim
RUN pip install quelltest fastapi uvicorn PyJWT cryptography
CMD ["uvicorn", "quell.github.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

```bash
docker build -t quell-app .
docker run -p 8080:8080 \
  -e GITHUB_APP_ID=123456 \
  -e GITHUB_APP_PRIVATE_KEY="$(cat your-app.pem | awk 'NF {printf "%s\\n", $0}')" \
  -e GITHUB_WEBHOOK_SECRET=your-secret \
  quell-app
```

**Run locally for testing:**

```bash
pip install quelltest fastapi uvicorn PyJWT cryptography
export GITHUB_APP_ID=123456
export GITHUB_APP_PRIVATE_KEY="$(cat your-app.pem | awk 'NF {printf "%s\\n", $0}')"
export GITHUB_WEBHOOK_SECRET=your-secret
uvicorn quell.github.app:app --host 0.0.0.0 --port 8080
```

Use [ngrok](https://ngrok.com) to expose localhost for webhook testing:

```bash
ngrok http 8080
# Update Webhook URL in App settings to the https ngrok URL
```

### 2.4 Verify the webhook

In the GitHub App settings → **Advanced** → **Recent Deliveries**, you should
see a `ping` event with a `200` response after saving the webhook URL. If you
see `403`, check the webhook secret. If you see `502`, the server isn't running.

### 2.5 Install the App on repositories

1. GitHub App settings → **Install App** → select **All repositories** or pick
   specific ones.
2. Open (or re-open) any pull request in an installed repo.
3. The App fetches the changed `.py` files via GitHub API, runs the guard-clause
   scanner, and posts a comment — no repo clone, no code sent to any external
   service.

### 2.6 How it works (architecture)

```
GitHub sends pull_request webhook
    ↓
HMAC-SHA256 signature check (rejects tampered payloads)
    ↓
Exchange App JWT for installation token (scoped to one repo, 1-hour TTL)
    ↓
Fetch changed .py files via GitHub Contents API (no clone)
    ↓
CodeGuardReader scans each file (pure AST, offline)
    ↓
CoverageChecker marks which guards already have tests
    ↓
Post / update a single PR comment (idempotent — never spams)
```

---

## Option 3 — `quell pr` command (local, one-off)

Run a scan against any open PR from your terminal. Useful for reviewing
before merging without setting up CI.

```bash
# Set your token once
export GITHUB_TOKEN=ghp_your_personal_access_token

# Analyse PR #42 in the current repo
quell pr 42

# Specify repo explicitly
quell pr 42 --repo owner/reponame

# Post the result as a PR comment
quell pr 42 --comment

# JSON output (for scripting)
quell pr 42 --format json
```

**Token scopes needed:** `repo` (read) + `pull_requests` (read) + if using
`--comment`: `issues` (write).

Get a token at **github.com → Settings → Developer settings → Personal access
tokens → Fine-grained tokens**.

---

## Comparison

| | GitHub Action | GitHub App | `quell pr` |
|--|:---:|:---:|:---:|
| Setup | Copy one YAML file | Create App + deploy server | `pip install quelltest` |
| Works without a server | ✅ | ✗ | ✅ |
| Covers all repos automatically | ✗ | ✅ | ✗ |
| Inline diff annotations | ✅ | ✗ | ✗ |
| PR comment | ✅ | ✅ | ✅ |
| Block merges on gaps | ✅ | ✗ | ✗ |
| No code leaves your infra | ✅ | ✅ | ✅ |

**Recommendation:** start with the GitHub Action (Option 1). It takes 2 minutes,
needs no server, and works per-repo. Upgrade to the GitHub App if you want
zero-config coverage across many repos or an org-wide policy.

---

## Troubleshooting

**Action posts no comment:**
- Check `permissions: pull-requests: write` is in the workflow.
- The comment step only fires on `pull_request` events, not `push`.

**`403 Forbidden` on webhook:**
- The webhook secret in the App settings doesn't match `GITHUB_WEBHOOK_SECRET`.
- Regenerate the secret in both places.

**`No guard clauses found` comment:**
- Quell only scans `.py` files that were added or modified in the PR diff.
- If the PR only touches tests, config, or non-Python files, nothing is reported.

**Webhook delivers `500`:**
- The `GITHUB_APP_PRIVATE_KEY` newlines are wrong. The value must use literal
  `\n` between PEM lines, not real newlines, when set via environment variable.
- Check server logs — `uvicorn` prints the full traceback.

**GitHub App installed but no comment appears:**
- Check **App settings → Advanced → Recent Deliveries** for errors.
- Make sure **Pull request** is checked under **Subscribe to events**.
- The App only scans Python files (`*.py`) that are `added` or `modified`.
  If the PR touches only non-Python files, it exits silently.
