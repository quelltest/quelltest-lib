"""
Generates SVG badges for Quell Score, mimicking shields.io style.

Usage:
    from quell.score.badge import generate_badge
    svg = generate_badge(score=0.87)
    Path(".quell/badge.svg").write_text(svg)

Embed in README:
    ![Quell Score](.quell/badge.svg)
"""
from __future__ import annotations
from pathlib import Path


def generate_badge(score: float) -> str:
    """
    Generate a shields.io-style SVG badge for the given mutation score.

    Args:
        score: float from 0.0 to 1.0

    Returns:
        SVG string ready to write to a .svg file.
    """
    pct = int(score * 100)

    if score >= 0.80:
        color = "#4c1"       # green
    elif score >= 0.60:
        color = "#dfb317"    # yellow
    else:
        color = "#e05d44"    # red

    label = "quell score"
    value = f"{pct}%"

    label_width = len(label) * 6 + 10
    value_width = len(value) * 6 + 10
    total_width = label_width + value_width

    label_center = label_width * 5        # in 0.1px units for scale(.1)
    value_center = (label_width + value_width / 2) * 10

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{total_width}" height="20">\n'
        f'  <linearGradient id="s" x2="0" y2="100%">\n'
        f'    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        f'    <stop offset="1" stop-opacity=".1"/>\n'
        f'  </linearGradient>\n'
        f'  <clipPath id="r">\n'
        f'    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>\n'
        f'  </clipPath>\n'
        f'  <g clip-path="url(#r)">\n'
        f'    <rect width="{label_width}" height="20" fill="#555"/>\n'
        f'    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>\n'
        f'    <rect width="{total_width}" height="20" fill="url(#s)"/>\n'
        f'  </g>\n'
        f'  <g fill="#fff" text-anchor="middle" '
        f'font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="110">\n'
        f'    <text x="{label_center}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)">{label}</text>\n'
        f'    <text x="{label_center}" y="140" transform="scale(.1)">{label}</text>\n'
        f'    <text x="{value_center}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)">{value}</text>\n'
        f'    <text x="{value_center}" y="140" transform="scale(.1)">{value}</text>\n'
        f'  </g>\n'
        f'</svg>'
    )


def write_badge(score: float, output_dir: Path = Path(".quell")) -> Path:
    """
    Write badge SVG to output_dir/badge.svg. Creates the directory if needed.

    Returns the path to the written badge.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    badge_path = output_dir / "badge.svg"
    badge_path.write_text(generate_badge(score), encoding="utf-8")
    return badge_path
