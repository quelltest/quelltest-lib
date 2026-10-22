"""The CLI reference docs must describe the CLI that actually ships."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from quell.cli import app

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_has_pr_flag_and_no_action_flag():
    result = runner.invoke(app, ["install", "--help"])
    assert result.exit_code == 0
    assert "--pr" in result.output
    assert "--action" not in result.output


def test_docs_do_not_document_install_action_flag():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
        if "install --action" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"these files document a flag that does not exist: {offenders}"


def test_docs_do_not_describe_removed_commands_as_working():
    text = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "still work" not in text
