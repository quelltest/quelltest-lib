"""Regression tests for hints and docs that name removed or non-existent CLI surface.

`quell scan` and `quell check` were removed in v1.2 and exit 1. Anything that
tells a user to run them sends them straight into that error. Likewise
`quell install` has `--hook` and `--pr`; there is no `--action`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quell.cli import app
from quell.env.detector import ENVIRONMENT_STRATEGY, RuntimeEnvironment
from quell.github.pr_runner import GitHubPRRunner

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]

# A command a user is told to run: `quell scan ...` / `quell check ...`.
REMOVED_COMMAND = re.compile(r"quell (scan|check)\b")

_GAP = {
    "file": "app/svc.py",
    "function": "charge",
    "description": "amount must be positive",
    "kind": "boundary",
    "line": 2,
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text(
        "def charge(amount: int) -> int:\n"
        "    if amount <= 0:\n"
        "        raise ValueError('amount must be positive')\n"
        "    return amount\n",
        encoding="utf-8",
    )
    return tmp_path


def test_find_hint_points_at_quell_find(project: Path, monkeypatch):
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["find", "app/", "--root", str(project)])
    assert result.exit_code == 0
    assert "--fix" in result.output
    assert not REMOVED_COMMAND.search(result.output), result.output
    assert "quell find app --fix" in result.output.replace("\n", " ")


def test_github_app_comment_points_at_quell_find():
    # quell.github.app cannot be imported at the moment (its import chain hits
    # quell.ci, which is broken independently of this change), so check the
    # template source instead of calling _format_app_comment.
    text = (REPO_ROOT / "quell" / "github" / "app.py").read_text(encoding="utf-8")
    assert not REMOVED_COMMAND.search(text)
    assert "**Fix locally:** `quell find" in text


def test_pr_command_hint_points_at_quell_find():
    text = (REPO_ROOT / "quell" / "cli.py").read_text(encoding="utf-8")
    assert "Fix locally:[/yellow] quell find" in text
    assert "Fix locally:[/yellow] quell check" not in text


def test_pr_runner_comment_points_at_quell_find():
    pr_runner = GitHubPRRunner(pr_number=1, repo="o/r", token="x")
    body = pr_runner._format_comment(
        {
            "score": 0.5,
            "gaps": [_GAP],
            "total_requirements": 2,
            "pr_number": 1,
            "pr_title": "t",
        }
    )
    assert "Fix locally" in body
    assert not REMOVED_COMMAND.search(body), body
    assert "quell find" in body


def test_environment_hints_do_not_name_removed_commands():
    for env, strategy in ENVIRONMENT_STRATEGY.items():
        hint = strategy.ci_setup_hint or ""
        assert not REMOVED_COMMAND.search(hint), f"{env}: {hint}"
    assert RuntimeEnvironment.KUBERNETES_POD in ENVIRONMENT_STRATEGY


def test_action_yml_does_not_run_removed_commands():
    text = (REPO_ROOT / "action.yml").read_text(encoding="utf-8")
    assert not REMOVED_COMMAND.search(text)
    assert "quell find" in text


def test_docs_github_integration_points_at_quell_find():
    text = (REPO_ROOT / "docs" / "github-integration.md").read_text(encoding="utf-8")
    assert not REMOVED_COMMAND.search(text)
