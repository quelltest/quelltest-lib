"""Tests for removed quell scan / quell check commands (spec8 §2.2, issue #119)."""
from __future__ import annotations

from typer.testing import CliRunner

from quell.cli import app

runner = CliRunner()


def test_scan_exits_with_code_1() -> None:
    result = runner.invoke(app, ["scan", "src/"])
    assert result.exit_code == 1


def test_scan_prints_removal_message() -> None:
    result = runner.invoke(app, ["scan"])
    assert "removed in v1.2" in result.output
    assert "quell find" in result.output


def test_check_exits_with_code_1() -> None:
    result = runner.invoke(app, ["check", "src/"])
    assert result.exit_code == 1


def test_check_prints_removal_message() -> None:
    result = runner.invoke(app, ["check"])
    assert "removed in v1.2" in result.output
    assert "quell find" in result.output


def test_find_still_works() -> None:
    """quell find must be unaffected by the removal of scan/check."""
    result = runner.invoke(app, ["find", "--help"])
    assert result.exit_code == 0
    assert "Find untested edge cases" in result.output
