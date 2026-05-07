"""Tests for quell/score/badge.py"""
import re
import tempfile
from pathlib import Path

import pytest

from quell.score.badge import generate_badge, write_badge


def test_generate_badge_is_valid_svg():
    svg = generate_badge(0.87)
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_generate_badge_green_above_80():
    svg = generate_badge(0.85)
    assert "#4c1" in svg
    assert "85%" in svg


def test_generate_badge_yellow_between_60_and_80():
    svg = generate_badge(0.72)
    assert "#dfb317" in svg
    assert "72%" in svg


def test_generate_badge_red_below_60():
    svg = generate_badge(0.45)
    assert "#e05d44" in svg
    assert "45%" in svg


def test_generate_badge_boundary_exactly_80():
    svg = generate_badge(0.80)
    assert "#4c1" in svg


def test_generate_badge_boundary_exactly_60():
    svg = generate_badge(0.60)
    assert "#dfb317" in svg


def test_generate_badge_zero_score():
    svg = generate_badge(0.0)
    assert "#e05d44" in svg
    assert "0%" in svg


def test_generate_badge_full_score():
    svg = generate_badge(1.0)
    assert "#4c1" in svg
    assert "100%" in svg


def test_generate_badge_contains_label():
    svg = generate_badge(0.90)
    assert "quell score" in svg


def test_write_badge_creates_file(tmp_path):
    badge_path = write_badge(0.75, tmp_path)
    assert badge_path.exists()
    assert badge_path.suffix == ".svg"
    content = badge_path.read_text()
    assert "<svg" in content


def test_write_badge_creates_directory(tmp_path):
    nested = tmp_path / "a" / "b" / ".quell"
    badge_path = write_badge(0.60, nested)
    assert badge_path.exists()


def test_generate_badge_has_correct_width():
    """Badge width should be positive and contain width attribute."""
    svg = generate_badge(0.88)
    match = re.search(r'width="(\d+)"', svg)
    assert match is not None
    width = int(match.group(1))
    assert width > 0
