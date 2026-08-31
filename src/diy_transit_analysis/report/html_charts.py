"""Shared inline-SVG chart/table rendering + base CSS for the self-contained HTML reports.

Used by report/dashboard.py and report/ntd.py so both stay visually
consistent and neither re-implements the same SVG string-building —
per specs/architecture.md#the-report-html-dashboards-rendering-approach.
No charting library, no JavaScript framework, no CDN font or script.
"""

from __future__ import annotations

import math
from html import escape

SERIES_COLOR_LIGHT = "#2a78d6"
SERIES_COLOR_DARK = "#3987e5"

# Shared page shell: color-scheme variables, layout, stat tiles, charts,
# and data tables. Each report's own <style> block embeds this verbatim
# and may append page-specific rules after it.
BASE_CSS = """
  :root {
    color-scheme: light;
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --gridline: #e1e0d9;
    --baseline: #c3c2b7;
    --series-1: """ + SERIES_COLOR_LIGHT + """;
    --series-1-fill: rgba(42, 120, 214, 0.10);
    --border: rgba(11,11,11,0.10);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --gridline: #2c2c2a;
      --baseline: #383835;
      --series-1: """ + SERIES_COLOR_DARK + """;
      --series-1-fill: rgba(57, 135, 229, 0.14);
      --border: rgba(255,255,255,0.10);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main { max-width: 880px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); margin: 0 0 24px; }
  .section {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 20px;
  }
  .section h2 { font-size: 1.05rem; margin: 0 0 12px; }
  .subsection-title { font-size: 0.85rem; color: var(--text-secondary); margin: 16px 0 6px; font-weight: 600; }
  .section-note { color: var(--text-secondary); font-size: 0.9rem; }
  .stat-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
  .stat-tile {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 16px;
    min-width: 150px;
    flex: 1 1 150px;
  }
  .stat-label { color: var(--text-secondary); font-size: 0.82rem; }
  .stat-value { font-size: 1.5rem; font-weight: 600; margin-top: 2px; }
  .stat-note { color: var(--text-muted); font-size: 0.78rem; margin-top: 2px; }
  .chart { width: 100%; height: auto; overflow: visible; }
  .chart .gridline { stroke: var(--gridline); stroke-width: 1; }
  .chart .axis-label { fill: var(--text-muted); font-size: 9px; }
  .chart .area-fill { fill: var(--series-1-fill); stroke: none; }
  .chart .line { fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .chart .peak-dot { fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; }
  .chart .peak-label { fill: var(--text-primary); font-size: 10px; font-weight: 600; }
  .chart .hit-point { fill: transparent; cursor: pointer; }
  .chart .hit-point:focus, .chart .hit-point:hover { fill: var(--series-1); opacity: 0.35; outline: none; }
  .chart .crosshair { stroke: var(--baseline); stroke-width: 1; }
  .chart-tooltip {
    position: absolute;
    pointer-events: none;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 0.8rem;
    color: var(--text-primary);
    display: none;
    white-space: nowrap;
  }
  .chart-wrap { position: relative; }
  details.data-table { margin-top: 8px; }
  details.data-table summary { cursor: pointer; color: var(--text-secondary); font-size: 0.85rem; }
  details.data-table table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.85rem; }
  details.data-table th, details.data-table td {
    text-align: left;
    padding: 4px 8px;
    border-bottom: 1px solid var(--gridline);
  }
  details.data-table th { color: var(--text-secondary); font-weight: 600; }
"""

# Dependency-free hover/crosshair <script>, shared verbatim by every chart
# on the page — every value it can show is also present in the data-table
# <details> next to each chart, so the page degrades to fully static
# (still fully readable) with JavaScript disabled.
HOVER_SCRIPT = """
(function () {
  document.querySelectorAll(".chart").forEach(function (svg) {
    var tooltip = document.querySelector('.chart-tooltip[data-for="' + svg.id + '"]');
    var crosshair = svg.querySelector(".crosshair");
    var wrap = svg.closest(".chart-wrap");
    function show(point) {
      var label = point.getAttribute("data-label");
      var value = point.getAttribute("data-value");
      if (tooltip) {
        tooltip.textContent = label + ": " + value;
        tooltip.style.display = "block";
        var rect = wrap.getBoundingClientRect();
        var svgRect = svg.getBoundingClientRect();
        var scaleX = svgRect.width / svg.viewBox.baseVal.width;
        var scaleY = svgRect.height / svg.viewBox.baseVal.height;
        var cx = (svgRect.left - rect.left) + point.getAttribute("cx") * scaleX;
        var cy = (svgRect.top - rect.top) + point.getAttribute("cy") * scaleY;
        tooltip.style.left = Math.max(0, cx - 20) + "px";
        tooltip.style.top = Math.max(0, cy - 32) + "px";
      }
      if (crosshair) {
        crosshair.setAttribute("x1", point.getAttribute("cx"));
        crosshair.setAttribute("x2", point.getAttribute("cx"));
        crosshair.style.display = "block";
      }
    }
    function hide() {
      if (tooltip) tooltip.style.display = "none";
      if (crosshair) crosshair.style.display = "none";
    }
    svg.querySelectorAll(".hit-point").forEach(function (point) {
      point.addEventListener("mouseenter", function () { show(point); });
      point.addEventListener("focus", function () { show(point); });
      point.addEventListener("mouseleave", hide);
      point.addEventListener("blur", hide);
    });
  });
})();
"""


def nice_ticks(max_value: int, target_count: int = 5) -> list[int]:
    """Evenly-spaced, round-number y-axis ticks from 0 up past max_value.

    All chart data here is non-negative counts, so ticks are always whole
    numbers — avoids the classic duplicate-label bug where rounding
    fractional ticks (e.g. 0, 0.29, 0.575, 0.8625, 1.15) collapses several
    distinct ticks to the same displayed integer.
    """
    if max_value <= 0:
        return [0, 1]
    if max_value <= target_count:
        return list(range(max_value + 1))
    raw_step = max_value / target_count
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = magnitude
    for m in (1, 2, 5, 10):
        step = m * magnitude
        if step >= raw_step:
            break
    step = max(round(step), 1)
    top = -(-max_value // step) * step  # ceil to a multiple of step
    return list(range(0, top + step, step))


def thin_indices(n: int, max_ticks: int = 8) -> list[int]:
    """Evenly-spaced indices (always including the first and last) for x-axis labels."""
    if n <= max_ticks:
        return list(range(n))
    step = (n - 1) / (max_ticks - 1)
    return sorted({round(i * step) for i in range(max_ticks)})


def area_chart_svg(*, chart_id: str, points: list[tuple[str, int]], value_suffix: str = "") -> str:
    """A single-series area+line chart. points: list of (x_label, y_value)."""
    width, height = 720, 220
    pad_left, pad_right, pad_top, pad_bottom = 44, 12, 16, 28
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    values = [v for _, v in points]
    max_value = max(values) if values else 0
    ticks = nice_ticks(max_value)
    y_max = ticks[-1]
    n = len(points)

    def x_at(i: int) -> float:
        return pad_left if n <= 1 else pad_left + chart_w * i / (n - 1)

    def y_at(v: int) -> float:
        return pad_top + chart_h * (1 - v / y_max)

    baseline_y = pad_top + chart_h
    coords = [(x_at(i), y_at(v)) for i, (_, v) in enumerate(points)]

    line_path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    area_path = line_path
    if coords:
        area_path += f" L{coords[-1][0]:.1f},{baseline_y:.1f} L{coords[0][0]:.1f},{baseline_y:.1f} Z"

    gridlines = []
    for tick in ticks:
        y = y_at(tick)
        gridlines.append(
            f'<line class="gridline" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" />'
            f'<text class="axis-label" x="{pad_left - 6}" y="{y + 4:.1f}" text-anchor="end">{tick}</text>'
        )

    tick_indices = thin_indices(n)
    x_ticks = [
        f'<text class="axis-label" x="{x_at(i):.1f}" y="{height - 6}" text-anchor="middle">{escape(points[i][0])}</text>'
        for i in tick_indices
    ]

    hit_points = []
    for i, (label, value) in enumerate(points):
        x, y = coords[i]
        hit_points.append(
            f'<circle class="hit-point" tabindex="0" role="img" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="10" '
            f'data-label="{escape(label)}" data-value="{value}{value_suffix}">'
            f"<title>{escape(label)}: {value}{value_suffix}</title></circle>"
        )

    peak_marker = ""
    if values:
        peak_i = values.index(max_value)
        px, py = coords[peak_i]
        # Anchor the label away from the chart edge so it doesn't clip
        # when the peak falls on (or near) the first/last point.
        anchor = "start" if peak_i < n * 0.1 else "end" if peak_i > n * 0.9 else "middle"
        peak_marker = (
            f'<circle class="peak-dot" cx="{px:.1f}" cy="{py:.1f}" r="4" />'
            f'<text class="peak-label" x="{px:.1f}" y="{max(py - 10, pad_top + 10):.1f}" text-anchor="{anchor}">'
            f"{max_value}{value_suffix}</text>"
        )

    return f"""
<svg class="chart" id="{chart_id}" viewBox="0 0 {width} {height}" role="img"
     aria-label="{escape(chart_id)} chart">
  {''.join(gridlines)}
  <path class="area-fill" d="{area_path}" />
  <path class="line" d="{line_path}" />
  {peak_marker}
  {''.join(x_ticks)}
  {''.join(hit_points)}
  <line class="crosshair" x1="0" y1="{pad_top}" x2="0" y2="{baseline_y}" style="display:none" />
</svg>
""".strip()


def stat_tile(label: str, value: str, note: str | None = None) -> str:
    note_html = f'<div class="stat-note">{escape(note)}</div>' if note else ""
    return f"""
<div class="stat-tile">
  <div class="stat-label">{escape(label)}</div>
  <div class="stat-value">{escape(value)}</div>
  {note_html}
</div>
""".strip()


def data_table(headers: list[str], rows: list[tuple]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"""
<details class="data-table">
  <summary>Show data table</summary>
  <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
</details>
""".strip()


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def chart_with_tooltip(chart_html: str, *, chart_id: str) -> str:
    """Wrap a chart's SVG in the .chart-wrap + tooltip <div> the hover script targets."""
    return f"""
<div class="chart-wrap">
  {chart_html}
  <div class="chart-tooltip" data-for="{escape(chart_id)}"></div>
</div>
""".strip()
