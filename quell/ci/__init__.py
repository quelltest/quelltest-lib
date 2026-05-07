"""Quell CI — mutation testing + auto-fix pipeline for PR/CI usage."""
from quell.ci.diff_parser import get_changed_lines, ChangedLines
from quell.ci.runner import run_mutmut_full, run_mutmut_targeted
from quell.ci.threshold import check_threshold, ThresholdResult
from quell.ci.reporter import CIReport, report_console, report_json, report_github_actions

__all__ = [
    "get_changed_lines",
    "ChangedLines",
    "run_mutmut_full",
    "run_mutmut_targeted",
    "check_threshold",
    "ThresholdResult",
    "CIReport",
    "report_console",
    "report_json",
    "report_github_actions",
]
