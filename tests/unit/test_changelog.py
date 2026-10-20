"""CHANGELOG.md stays well-formed and in step with the package version."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADING = re.compile(r"^## (Unreleased|\d+(?:\.\d+){1,3}) ?(?:- (\d{4}-\d{2}-\d{2}))?$", re.MULTILINE)


def _headings() -> list[tuple[str, str | None]]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in HEADING.finditer(text)]


def test_every_release_heading_is_well_formed_and_unique() -> None:
    """Each `## ` heading is `Unreleased` or `<version> - <date>`, and no version repeats."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    all_h2 = re.findall(r"^## .*$", text, re.MULTILINE)
    headings = _headings()
    assert len(headings) == len(all_h2), "a '## ' heading does not match the release format"
    versions = [version for version, _ in headings]
    assert len(versions) == len(set(versions))
    for version, date in headings:
        assert (version == "Unreleased") == (date is None), f"{version}: dated releases need a date"


def test_unreleased_comes_first() -> None:
    """The Unreleased section, when present, is the first release heading."""
    versions = [version for version, _ in _headings()]
    assert "Unreleased" not in versions[1:]


def test_package_version_is_released_or_covered_by_unreleased() -> None:
    """pyproject's version is either a dated release in the changelog or work listed under Unreleased."""
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    versions = [v for v, _ in _headings()]
    assert version in versions or "Unreleased" in versions
