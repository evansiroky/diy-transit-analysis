"""Build the NTD Time Series HTML report.

Spec: specs/data-model.md#ntd-time-series-report-output

One section per configured `category` (fixed order: Service, Expenditure,
Funding, Asset), one chart per `ntd.time_series[]` entry, filtered to one
agency's `ntd_id`. Same self-contained inline-SVG rendering approach as
report/dashboard.py, via the shared report/html_charts.py helpers — see
specs/architecture.md#the-report-html-dashboards-rendering-approach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from diy_transit_analysis.config import NtdTimeSeriesSource
from diy_transit_analysis.ntd import timeseries
from diy_transit_analysis.report import html_charts

_CATEGORY_ORDER = ["service", "expenditure", "funding", "asset"]
_CATEGORY_LABELS = {
    "service": "Service",
    "expenditure": "Expenditure",
    "funding": "Funding",
    "asset": "Asset",
}


@dataclass(frozen=True)
class NtdChartData:
    name: str
    category: str
    series: list[tuple[int, float]]  # sorted by year; empty if no data for this ntd_id
    note: str | None  # set whenever series is empty, explaining why


@dataclass(frozen=True)
class NtdReportData:
    agency: str
    ntd_id: str
    min_year: int | None
    max_year: int | None
    charts_by_category: dict[str, list[NtdChartData]]


def build_ntd_report_data(
    sources: list[NtdTimeSeriesSource], raw_dir: Path, *, agency: str, ntd_id: str
) -> NtdReportData:
    """Build the report's data, independent of how it's rendered.

    Every configured source gets exactly one NtdChartData, even when its
    fetched file has no rows for this ntd_id (empty series + a note) — see
    specs/data-model.md#ntd-time-series-report-output. Raises
    ntd.timeseries.NtdDataError, uncaught, if a fetched file can't be
    parsed at all (no recognizable NTD ID column) — that's a loud failure,
    not a section to skip.
    """
    charts_by_category: dict[str, list[NtdChartData]] = {category: [] for category in _CATEGORY_ORDER}
    all_years: list[int] = []

    for source in sources:
        path = timeseries.fetched_path(source, raw_dir)
        if not path.exists():
            chart = NtdChartData(
                name=source.name,
                category=source.category,
                series=[],
                note=f"not yet fetched — run fetch-ntd (expected {path.name})",
            )
        else:
            series_by_year = timeseries.read_agency_series(path, ntd_id)
            if series_by_year:
                series = sorted(series_by_year.items())
                chart = NtdChartData(name=source.name, category=source.category, series=series, note=None)
                all_years.extend(year for year, _ in series)
            else:
                chart = NtdChartData(
                    name=source.name,
                    category=source.category,
                    series=[],
                    note=f"no data for NTD ID {ntd_id} in this file",
                )
        charts_by_category[source.category].append(chart)

    return NtdReportData(
        agency=agency,
        ntd_id=ntd_id,
        min_year=min(all_years) if all_years else None,
        max_year=max(all_years) if all_years else None,
        charts_by_category=charts_by_category,
    )


def _chart_id(category: str, index: int, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "chart"
    return f"ntd-{category}-{index}-{slug}"


def _render_chart(chart: NtdChartData, *, chart_id: str) -> str:
    if not chart.series:
        return f"""
<div class="section-note">{escape(chart.note or "no data")}</div>
""".strip()

    points = [(str(year), round(value)) for year, value in chart.series]
    svg = html_charts.area_chart_svg(chart_id=chart_id, points=points)
    table = html_charts.data_table(["Year", chart.name], chart.series)
    return f"""
{html_charts.chart_with_tooltip(svg, chart_id=chart_id)}
{table}
""".strip()


def render_html(data: NtdReportData) -> str:
    """Render the NTD Time Series report as a single self-contained HTML document (string)."""
    sections = []
    for category in _CATEGORY_ORDER:
        charts = data.charts_by_category.get(category, [])
        if not charts:
            continue
        chart_blocks = []
        for i, chart in enumerate(charts):
            chart_blocks.append(
                f"""
<h3 class="subsection-title">{escape(chart.name)}</h3>
{_render_chart(chart, chart_id=_chart_id(category, i, chart.name))}
""".strip()
            )
        sections.append(
            f"""
<section class="section">
  <h2>{escape(_CATEGORY_LABELS[category])}</h2>
  {"".join(chart_blocks)}
</section>
""".strip()
        )

    agency_escaped = escape(data.agency)
    ntd_id_escaped = escape(data.ntd_id)
    if data.min_year is not None and data.max_year is not None:
        year_range = f"{data.min_year}–{data.max_year}"
    else:
        year_range = "no data available for this NTD ID"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{agency_escaped} — NTD Time Series</title>
<style>
{html_charts.BASE_CSS}
</style>
</head>
<body>
<main>
  <h1>{agency_escaped}</h1>
  <p class="subtitle">
    NTD Time Series &middot; NTD ID {ntd_id_escaped} &middot; {year_range}
  </p>

  {"".join(sections)}
</main>
<script>
{html_charts.HOVER_SCRIPT}
</script>
</body>
</html>
"""


def write_html(html: str, output_dir: Path, agency: str, min_year: int | None, max_year: int | None) -> Path:
    """Write to <output_dir>/reports/<agency>/ntd-<min_year>-<max_year>.html.

    Falls back to "ntd-no-data.html" when every configured source came
    back with an empty series for this agency's ntd_id — per
    specs/data-model.md#ntd-time-series-report-output.
    """
    reports_dir = output_dir / "reports" / agency
    reports_dir.mkdir(parents=True, exist_ok=True)
    suffix = "no-data" if min_year is None or max_year is None else f"{min_year}-{max_year}"
    dest = reports_dir / f"ntd-{suffix}.html"
    dest.write_text(html)
    return dest
