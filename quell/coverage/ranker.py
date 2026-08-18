"""
Ranks and suppresses gaps so the default output is short and actionable.
(spec10 §4.2, issue #154)

The number this exists to fix
-----------------------------
A QA pass on a production backend got 170 flagged items, cross-referenced them
against the existing suite by hand, and found 3 genuine holes. About 1.8%
actionable. The engine found; a human did the ranking.

Those 167 were not wrong -- they are real guard clauses. They were not worth
acting on, and we had no way to say so. Google's Tricorder (CACM 2018) puts
the abandonment threshold near a 10% effective false-positive rate and holds
itself under 5%; at ~98% we were an order of magnitude outside the range where
anyone keeps a tool installed.

So this is a precision problem, not a correctness one, and the fix is to rank
and truncate -- but truncate the DISPLAY, never the analysis. `--all` always
shows everything, and every suppressed item stays in the report with the reason
it was suppressed. Hiding findings without saying so would be its own kind of
dishonesty.

Suppression signals, cheapest and strongest first:
  1. an existing test already executes the guard's line (measured, #142)
  2. the guard sits on a private function nothing else calls
Then survivors are ordered by blast radius, so the short list is the part a
reviewer would have picked out anyway.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

DEFAULT_DISPLAY_LIMIT = 10


class Suppression(StrEnum):
    """Why a real finding is not worth showing by default."""

    ALREADY_EXERCISED = "an existing test already executes this line"
    PRIVATE_UNCALLED = "private function with no callers in this project"


@dataclass
class RankedGap:
    """A gap plus why it is (or is not) worth a reviewer's attention."""

    requirement: Any
    score: float
    suppressed_by: Suppression | None = None
    reasons: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []

    @property
    def is_actionable(self) -> bool:
        return self.suppressed_by is None


def rank(
    requirements: list[Any],
    coverage_map: Any | None = None,
    public_names: set[str] | None = None,
    callers: dict[str, int] | None = None,
) -> list[RankedGap]:
    """Order gaps most-worth-reviewing first, marking suppressed ones.

    Nothing is dropped. Callers decide how many to display; the full list is
    always returned so the report keeps every finding.
    """
    ranked = [
        _score_one(req, coverage_map, public_names or set(), callers or {})
        for req in requirements
    ]
    # Actionable first, then by score. Suppressed items keep a stable order so
    # `--all` output does not reshuffle between runs.
    ranked.sort(key=lambda g: (g.suppressed_by is not None, -g.score))
    return ranked


def actionable(ranked: list[RankedGap]) -> list[RankedGap]:
    return [g for g in ranked if g.is_actionable]


def surfaced_ratio(ranked: list[RankedGap]) -> float:
    """Fraction of findings we surface rather than suppress.

    NOT precision. Precision in the Tricorder sense is "of what we show, how
    much does the developer act on", and that needs labelled ground truth we do
    not have here. This measures only how aggressively we suppress.

    The two move together -- suppressing the already-covered majority is what
    lifts precision -- but they are not the same number, and G3 is stated in
    terms of precision. Reporting this as precision would be the exact
    metric-mislabelling spec10 §0 exists because of.
    """
    if not ranked:
        return 0.0
    return len(actionable(ranked)) / len(ranked)


# ── internals ────────────────────────────────────────────────────────────────


def _score_one(
    req: Any,
    coverage_map: Any | None,
    public_names: set[str],
    callers: dict[str, int],
) -> RankedGap:
    gap = RankedGap(requirement=req, score=0.0)

    # 1. Measured execution is the strongest suppressor. A guard an existing
    #    test already runs is not a hole a reviewer needs to look at.
    if coverage_map is not None and getattr(req, "source_line", None):
        try:
            if coverage_map.is_line_covered(req.target_file, req.source_line):
                gap.suppressed_by = Suppression.ALREADY_EXERCISED
                gap.reasons.append(Suppression.ALREADY_EXERCISED.value)
                return gap
        except Exception:  # noqa: BLE001 — a bad map must not hide real gaps
            pass

    func = getattr(req, "target_function", "") or ""

    # 2. A private helper nothing calls cannot be reached from outside, so a
    #    missing test for its guard has no blast radius.
    if func.startswith("_") and callers.get(func, 0) == 0 and func not in public_names:
        gap.suppressed_by = Suppression.PRIVATE_UNCALLED
        gap.reasons.append(Suppression.PRIVATE_UNCALLED.value)
        return gap

    # ── blast radius ────────────────────────────────────────────────────────
    if func in public_names:
        gap.score += 3.0
        gap.reasons.append("public API surface")

    fan_in = callers.get(func, 0)
    if fan_in:
        gap.score += min(fan_in, 5) * 0.5
        gap.reasons.append(f"called from {fan_in} place(s)")

    if not func.startswith("_"):
        gap.score += 1.0

    kind = getattr(getattr(req, "constraint_kind", None), "value", "")
    if kind in ("must_raise", "not_null", "boundary"):
        # Guards that reject bad input protect a caller-facing contract.
        gap.score += 1.0
        gap.reasons.append(f"input-validation guard ({kind})")

    return gap


def public_names_for(project_root: Path) -> set[str]:
    """Top-level function names not prefixed with underscore.

    A cheap stand-in for "public API surface" that needs no import of the
    project. Returns an empty set on any error (invariant #6).
    """
    import ast
    import os

    names: set[str] = set()
    skip = {".venv", "venv", "__pycache__", ".git", "node_modules", "site-packages", ".tox"}
    try:
        for dirpath, dirnames, filenames in os.walk(project_root):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            for fn in filenames:
                if not fn.endswith(".py") or fn.startswith("test_"):
                    continue
                try:
                    tree = ast.parse(
                        Path(dirpath, fn).read_text(encoding="utf-8", errors="replace")
                    )
                except Exception:  # noqa: BLE001
                    continue
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_"):
                            names.add(node.name)
    except Exception:  # noqa: BLE001
        return set()
    return names
