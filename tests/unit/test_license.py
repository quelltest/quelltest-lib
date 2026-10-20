"""The project is licensed under Apache-2.0; every place that states a licence must agree."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_license_file_is_apache_2_0() -> None:
    """LICENSE is the unmodified Apache License 2.0 text and NOTICE names the copyright holder."""
    text = _read("LICENSE")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text
    assert "http://www.apache.org/licenses/LICENSE-2.0" in text
    assert "MIT License" not in text
    assert "Copyright 2026 Shashank Bindal" in _read("NOTICE")


def test_package_metadata_declares_apache_2_0() -> None:
    """pyproject.toml carries the SPDX id and the matching trove classifier, and no MIT leftovers."""
    project = tomllib.loads(_read("pyproject.toml"))["project"]
    assert project["license"] == {"text": "Apache-2.0"}
    classifiers = project["classifiers"]
    assert "License :: OSI Approved :: Apache Software License" in classifiers
    assert not [c for c in classifiers if "MIT" in c]


def test_other_statements_of_the_licence_agree() -> None:
    """README badge, llms.txt and the VS Code extension manifest all say Apache-2.0."""
    assert "License-Apache_2.0" in _read("README.md")
    assert "License: MIT" not in _read("README.md")
    assert "- License: Apache-2.0" in _read("llms.txt")
    assert json.loads(_read("vscode-quell/package.json"))["license"] == "Apache-2.0"
