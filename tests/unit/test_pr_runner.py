"""Tests for GitHubPRRunner — uses mock subprocess and HTTP."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from quell.github.pr_runner import GitHubPRRunner


def test_detect_repo_from_https_remote() -> None:
    runner = GitHubPRRunner.__new__(GitHubPRRunner)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "https://github.com/owner/myrepo.git\n"
        mock_run.return_value.returncode = 0
        assert runner._detect_repo() == "owner/myrepo"


def test_detect_repo_from_ssh_remote() -> None:
    runner = GitHubPRRunner.__new__(GitHubPRRunner)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "git@github.com:owner/myrepo.git\n"
        mock_run.return_value.returncode = 0
        assert runner._detect_repo() == "owner/myrepo"


def test_detect_repo_raises_on_non_github_remote() -> None:
    runner = GitHubPRRunner.__new__(GitHubPRRunner)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "https://gitlab.com/owner/repo.git\n"
        mock_run.return_value.returncode = 0
        with pytest.raises(RuntimeError, match="Cannot auto-detect"):
            runner._detect_repo()


def test_format_comment_no_gaps() -> None:
    runner = GitHubPRRunner(pr_number=1, repo="a/b", token="fake")
    report = {
        "pr_number": 1,
        "pr_title": "Test PR",
        "pr_author": "dev",
        "pr_url": "https://github.com/a/b/pull/1",
        "changed_files": ["payments.py"],
        "total_requirements": 3,
        "covered_requirements": 3,
        "gaps": [],
        "score": 1.0,
    }
    comment = runner._format_comment(report)
    assert "All 3 requirements" in comment
    assert "Quell Report" in comment


def test_format_comment_with_gaps() -> None:
    runner = GitHubPRRunner(pr_number=1, repo="a/b", token="fake")
    report = {
        "pr_number": 1, "pr_title": "Test", "pr_author": "dev",
        "pr_url": "https://github.com/a/b/pull/1",
        "changed_files": ["payments.py"],
        "total_requirements": 3, "covered_requirements": 1,
        "gaps": [
            {
                "file": "payments.py",
                "function": "pay",
                "description": "amount must be > 0",
                "kind": "boundary",
                "source": "type",
            },
        ],
        "score": 0.33,
    }
    comment = runner._format_comment(report)
    assert "amount must be > 0" in comment
    assert "Fix locally" in comment


def test_format_comment_truncates_beyond_10_gaps() -> None:
    runner = GitHubPRRunner(pr_number=1, repo="a/b", token="fake")
    gaps = [
        {"file": "f.py", "function": "func", "description": f"req {i}", "kind": "boundary", "source": "type"}
        for i in range(15)
    ]
    report = {
        "pr_number": 1, "pr_title": "Big PR", "pr_author": "dev",
        "pr_url": "https://github.com/a/b/pull/1",
        "changed_files": ["f.py"],
        "total_requirements": 15, "covered_requirements": 0,
        "gaps": gaps, "score": 0.0,
    }
    comment = runner._format_comment(report)
    assert "5 more" in comment
