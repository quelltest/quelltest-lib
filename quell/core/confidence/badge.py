"""SVG badge generator for Production Readiness Score (spec7 §2.6).

Usage:
  from quell.core.confidence.badge import generate_badge
  svg = generate_badge(84)   # returns SVG string
  Path('.quell/badge.svg').write_text(svg)
"""
from __future__ import annotations

_COLORS: dict[str, str] = {
    "green":  "#4c1",    # shields.io green
    "yellow": "#dfb317", # shields.io yellow
    "red":    "#e05d44", # shields.io red
}

_SVG_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total_w}" height="20" role="img" aria-label="Quell PRS: {score}%">
  <title>Quell PRS: {score}%</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_w}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{total_w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="110">
    <text x="{label_cx}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{label_tl}" lengthAdjust="spacing">{label}</text>
    <text x="{label_cx}" y="140" transform="scale(.1)" textLength="{label_tl}" lengthAdjust="spacing">{label}</text>
    <text x="{value_cx}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{value_tl}" lengthAdjust="spacing">{value}</text>
    <text x="{value_cx}" y="140" transform="scale(.1)" textLength="{value_tl}" lengthAdjust="spacing">{value}</text>
  </g>
</svg>"""


def generate_badge(prs: int, tier: str = "") -> str:
    """Return an SVG badge string for the given PRS score.

    prs  : 0–100 integer
    tier : "green" | "yellow" | "red" — inferred from score if not given
    """
    score = max(0, min(100, prs))
    if not tier:
        tier = _infer_tier(score)
    color = _COLORS.get(tier, _COLORS["red"])

    label = "Quell PRS"
    value = f"{score}%"

    label_w = 78
    value_w = max(36, len(value) * 7 + 10)
    total_w = label_w + value_w

    return _SVG_TEMPLATE.format(
        total_w=total_w,
        label_w=label_w,
        value_w=value_w,
        color=color,
        label=label,
        value=value,
        label_cx=int(label_w * 5),
        label_tl=max(10, (label_w - 10) * 10),
        value_cx=int((label_w + value_w / 2) * 10),
        value_tl=max(10, (value_w - 10) * 10),
        score=score,
    )


def _infer_tier(score: int) -> str:
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"
