"""
Fetches PR diff from GitHub and runs Quell on changed files.

Authentication:
  Reads GITHUB_TOKEN from environment (standard GitHub Actions token).
  Also accepts --token flag for local use with a personal access token.

  Get a personal token at: github.com/settings/tokens
  Needs: repo (read) + pull_requests (read) + issues (write for comments)

Usage:
  quell pr 42                         # show gaps for PR #42
  quell pr 42 --fix                   # generate tests locally
  quell pr 42 --comment               # post result as PR comment
  quell pr 42 --repo owner/repo       # specify repo (auto-detects from git remote)
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx


class GitHubPRRunner:
    """Fetches a PR's changed Python files and runs Quell on them."""

    def __init__(
        self,
        pr_number: int,
        repo: str | None = None,
        token: str | None = None,
        project_root: Path = Path("."),
    ):
        self.pr_number = pr_number
        self.repo = repo or self._detect_repo()
        self.token = (
            token
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("QUELL_GITHUB_TOKEN")
        )
        self.project_root = project_root
        self.api_base = f"https://api.github.com/repos/{self.repo}"

    def _detect_repo(self) -> str:
        """Auto-detect repo from git remote origin."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, check=True,
            )
            url = result.stdout.strip()
            if "github.com/" in url:
                repo = url.split("github.com/")[-1].replace(".git", "")
            elif "github.com:" in url:
                repo = url.split("github.com:")[-1].replace(".git", "")
            else:
                raise ValueError(f"Cannot parse GitHub repo from remote: {url}")
            return repo
        except Exception as e:
            raise RuntimeError(
                f"Cannot auto-detect GitHub repo. Use --repo owner/reponame\n{e}"
            )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_pr_info(self) -> dict[str, Any]:
        """Fetch PR metadata: title, author, base branch, head branch."""
        r = httpx.get(
            f"{self.api_base}/pulls/{self.pr_number}",
            headers=self._headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    def get_changed_python_files(self) -> list[str]:
        """Return list of Python source file paths changed in this PR."""
        r = httpx.get(
            f"{self.api_base}/pulls/{self.pr_number}/files",
            headers=self._headers(),
            params={"per_page": 100},
            timeout=10.0,
        )
        r.raise_for_status()
        files = r.json()
        return [
            f["filename"] for f in files
            if f["filename"].endswith(".py")
            and "test" not in f["filename"]
            and f["status"] in ("added", "modified")
        ]

    def get_file_content(self, file_path: str, ref: str) -> str:
        """Fetch file content at a specific git ref."""
        r = httpx.get(
            f"{self.api_base}/contents/{file_path}",
            headers=self._headers(),
            params={"ref": ref},
            timeout=10.0,
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["content"]).decode("utf-8")

    def run_quell_on_pr(self, config: Any = None) -> dict[str, Any]:
        """
        Main entry point.
        1. Fetch PR info and changed files via GitHub API
        2. Write changed files to a temp directory
        3. Run CodeGuardReader on them (reads if/raise patterns — no annotations needed)
        4. Return structured report dict
        """
        from quell.coverage.checker import CoverageChecker
        from quell.spec.code_guard_reader import CodeGuardReader

        pr_info = self.get_pr_info()
        head_sha = pr_info["head"]["sha"]
        changed_files = self.get_changed_python_files()

        if not changed_files:
            return {
                "pr_number": self.pr_number,
                "pr_title": pr_info["title"],
                "changed_files": [],
                "total_requirements": 0,
                "gaps": [],
                "score": 1.0,
            }

        all_requirements = []
        reader = CodeGuardReader()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)

            for file_path in changed_files:
                try:
                    content = self.get_file_content(file_path, head_sha)
                    tmp_file = tmp_root / file_path
                    tmp_file.parent.mkdir(parents=True, exist_ok=True)
                    tmp_file.write_text(content)
                    all_requirements.extend(reader.read(tmp_file))
                except Exception:
                    continue

        checker = CoverageChecker(self.project_root)
        all_requirements = checker.check(all_requirements)

        gaps = [r for r in all_requirements if not r.is_covered]
        total = len(all_requirements)
        covered = total - len(gaps)

        return {
            "pr_number": self.pr_number,
            "pr_title": pr_info["title"],
            "pr_author": pr_info["user"]["login"],
            "pr_url": pr_info["html_url"],
            "changed_files": changed_files,
            "total_requirements": total,
            "covered_requirements": covered,
            "gaps": [
                {
                    "file": r.target_file.name,
                    "function": r.target_function,
                    "description": r.description,
                    "kind": r.constraint_kind.value,
                    "source": r.source.value,
                    "line": r.source_line,
                }
                for r in gaps
            ],
            "score": covered / total if total else 1.0,
        }

    def post_comment(self, report: dict[str, Any]) -> None:
        """Post Quell report as a comment on the PR."""
        if not self.token:
            raise RuntimeError(
                "GitHub token required for posting comments.\n"
                "Set GITHUB_TOKEN env var or use --token flag."
            )

        body = self._format_comment(report)

        r = httpx.get(
            f"{self.api_base}/issues/{self.pr_number}/comments",
            headers=self._headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        comments = r.json()
        existing = next(
            (c for c in comments if "Quell Report" in c.get("body", "")),
            None,
        )

        if existing:
            httpx.patch(
                f"{self.api_base}/issues/comments/{existing['id']}",
                headers=self._headers(),
                json={"body": body},
                timeout=10.0,
            ).raise_for_status()
        else:
            httpx.post(
                f"{self.api_base}/issues/{self.pr_number}/comments",
                headers=self._headers(),
                json={"body": body},
                timeout=10.0,
            ).raise_for_status()

    def _format_comment(self, report: dict[str, Any]) -> str:
        """Format the PR comment markdown."""
        score = report["score"]
        emoji = "\U0001f7e2" if score >= 0.8 else "\U0001f7e1" if score >= 0.5 else "\U0001f534"
        gaps = report["gaps"]
        total = report["total_requirements"]

        lines = [f"## {emoji} Quell Report — PR #{report['pr_number']}\n"]
        lines.append(f"**{report['pr_title']}**\n")

        if total == 0:
            lines.append("No type or docstring requirements found in changed files.\n")
        elif not gaps:
            lines.append(f"All {total} requirements in changed files are tested.\n")
        else:
            pct = int(score * 100)
            lines.append(
                f"Requirement coverage: **{pct}%** "
                f"({total - len(gaps)}/{total} covered)\n"
            )
            lines.append(
                f"\nFound **{len(gaps)} untested "
                f"requirement{'s' if len(gaps) > 1 else ''}:**\n"
            )
            lines.append("| File | Function | Requirement | Type |")
            lines.append("|------|----------|-------------|------|")
            for g in gaps[:10]:
                lines.append(
                    f"| `{g['file']}` | `{g['function']}` "
                    f"| {g['description']} | {g['kind']} |"
                )
            if len(gaps) > 10:
                lines.append(f"\n_...and {len(gaps) - 10} more._")
            lines.append("\n**Fix locally:** `quell check src/ --fix`")

        from quell import __version__
        lines.append(
            f"\n<sub>Quell v{__version__} • "
            f"rule-based, no code sent anywhere • "
            f"[quell.buildsbyshashank.tech](https://quell.buildsbyshashank.tech)</sub>"
        )
        return "\n".join(lines)
