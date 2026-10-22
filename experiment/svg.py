"""Grouped bar charts as SVG, with no dependency: Chapter 12's charts (T7.4).

The colours are the testing chapter's (scripts/report/testing_figures.py), assigned to series in
a fixed order. Bars show a mean, and the whisker one standard deviation either side of it, when
there is more than one repetition. Every value is drawn from the numbers passed in; nothing is
smoothed or estimated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from xml.sax.saxutils import escape

#: Categorical slots, in order: the same four the testing chapter's figures use.
SLOTS: Final = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#7d5bc6", "#5c6670")
INK: Final = "#1f2328"
SECONDARY: Final = "#57606a"
GRID: Final = "#d8dee4"
SURFACE: Final = "#ffffff"


@dataclass(frozen=True)
class Series:
    """One series: a value (and optional spread) per category, None where there is no value."""

    label: str
    values: Sequence[float | None]
    spreads: Sequence[float | None] = ()


def grouped_bars(
    title: str,
    categories: Sequence[str],
    series: Sequence[Series],
    y_label: str,
    width: int = 720,
    height: int = 360,
) -> str:
    """A grouped bar chart: categories along the axis, one bar per series in each."""
    if not categories or not series:
        raise ValueError("a chart needs at least one category and one series")
    if len(series) > len(SLOTS):
        raise ValueError(f"at most {len(SLOTS)} series; fold the rest together")
    for one in series:
        if len(one.values) != len(categories):
            raise ValueError(
                f"series {one.label!r} has {len(one.values)} values, "
                f"for {len(categories)} categories"
            )

    left, right, top, bottom = 64, 16, 48, 72
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max(
        [
            (v or 0) + (s or 0)
            for one in series
            for v, s in zip(one.values, _spreads(one), strict=True)
        ]
        + [0.0]
    )
    top_value, step = _axis(peak)
    scale = plot_h / top_value if top_value else 0.0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{left}" y="24" font-size="15" font-weight="600" fill="{INK}">'
        f"{escape(title)}</text>",
    ]
    # Gridlines and their labels: recessive, so the bars carry the reading.
    tick = 0.0
    while tick <= top_value + 1e-9:
        y = top + plot_h - tick * scale
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="{GRID}"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{y + 4:.1f}" font-size="11" text-anchor="end" '
            f'fill="{SECONDARY}">{_number(tick)}</text>'
        )
        tick += step
    parts.append(
        f'<text x="14" y="{top + plot_h / 2:.1f}" font-size="12" fill="{SECONDARY}" '
        f'transform="rotate(-90 14 {top + plot_h / 2:.1f})" text-anchor="middle">'
        f"{escape(y_label)}</text>"
    )

    group_w = plot_w / len(categories)
    bar_w = min(36.0, group_w * 0.8 / len(series))
    for c, category in enumerate(categories):
        start = left + c * group_w + (group_w - bar_w * len(series)) / 2
        for s, one in enumerate(series):
            value, spread = one.values[c], _spreads(one)[c]
            if value is None:
                continue
            x, h = start + s * bar_w, value * scale
            parts.append(
                f'<rect x="{x + 1:.1f}" y="{top + plot_h - h:.1f}" width="{bar_w - 2:.1f}" '
                f'height="{h:.1f}" rx="2" fill="{SLOTS[s]}"><title>{escape(one.label)}, '
                f"{escape(category)}: {_number(value)}</title></rect>"
            )
            if spread:
                cx, y1, y2 = (
                    x + bar_w / 2,
                    top + plot_h - (value + spread) * scale,
                    top + plot_h - max(0.0, value - spread) * scale,
                )
                parts.append(
                    f'<line x1="{cx:.1f}" y1="{y1:.1f}" x2="{cx:.1f}" y2="{y2:.1f}" '
                    f'stroke="{INK}" stroke-width="1.2"/>'
                )
        parts.append(
            f'<text x="{left + (c + 0.5) * group_w:.1f}" y="{top + plot_h + 18}" font-size="12" '
            f'text-anchor="middle" fill="{INK}">{escape(category)}</text>'
        )
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" '
        f'stroke="{SECONDARY}"/>'
    )

    # The legend, in series order, below the axis.
    x = float(left)
    for s, one in enumerate(series):
        parts.append(
            f'<rect x="{x:.1f}" y="{height - 26}" width="12" height="12" rx="2" fill="{SLOTS[s]}"/>'
        )
        parts.append(
            f'<text x="{x + 17:.1f}" y="{height - 16}" font-size="12" fill="{INK}">'
            f"{escape(one.label)}</text>"
        )
        x += 30 + 7 * len(one.label)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _spreads(one: Series) -> Sequence[float | None]:
    return one.spreads if one.spreads else [None] * len(one.values)


def _axis(peak: float) -> tuple[float, float]:
    """A round top for the axis and the step between gridlines, about five of them."""
    if peak <= 0:
        return 1.0, 0.25
    raw = peak / 5
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    return math.ceil(peak / step) * step, step


def _number(value: float) -> str:
    return (
        f"{value:.0f}"
        if abs(value - round(value)) < 1e-9
        else f"{value:.2f}".rstrip("0").rstrip(".")
    )
