"""Build the static HTML dashboard report.

Spec: specs/data-model.md#static-html-dashboard-report-output

Combines schedule-based stats (always available, GTFS-only) with
TIDES-based benchmark stats (only when the agency has tides: +
date_range: configured and TIDES has been fetched). Renders as a single
self-contained HTML file — inline SVG charts, no JS framework, no CDN —
per specs/architecture.md#the-report-html-dashboards-rendering-approach.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import gtfs_kit as gk
import pandas as pd

from diy_transit_analysis.report import on_time_performance as otp
from diy_transit_analysis.report import schedule_stats

_SERIES_COLOR_LIGHT = "#2a78d6"
_SERIES_COLOR_DARK = "#3987e5"

# ETA Accuracy Benchmark (https://github.com/TransitApp/ETA-Accuracy-Benchmark):
# four time-to-arrival buckets, each with its own asymmetric early/late
# tolerance. Order matches the source spec's own presentation (farthest
# out first). (label, bucket_low_min, bucket_high_min, early_tolerance,
# late_tolerance) — bucket range is [low, high) minutes-to-actual-arrival
# at the moment the prediction was sampled; tolerance is inclusive on
# both ends, per specs/data-model.md#eta-accuracy.
_ACCURACY_BUCKETS = [
    ("10-15 min away", 10, 15, timedelta(minutes=1.5), timedelta(minutes=4.5)),
    ("6-10 min away", 6, 10, timedelta(minutes=1), timedelta(minutes=3.5)),
    ("3-6 min away", 3, 6, timedelta(minutes=1), timedelta(minutes=2.5)),
    ("0-3 min away", 0, 3, timedelta(minutes=0.5), timedelta(minutes=1.5)),
]

# ETA Completeness Benchmark's "0-15 minutes out" qualifying window for a
# prediction — the union of the four accuracy buckets above.
# https://github.com/SwiftlyInc/ETA-Completeness-Benchmark
_COMPLETENESS_PREDICTION_WINDOW = (timedelta(minutes=0), timedelta(minutes=15))

_TRIP_STOP_OUTCOME_COLUMNS = {
    "service_date",
    "trip_id",
    "stop_id",
    "vehicle_assigned",
    "trip_cancelled",
    "stop_skipped",
}
_PREDICTIONS_COLUMNS = {"service_date", "trip_id", "stop_id", "sampled_at", "predicted_arrival"}
_ID_DTYPES = {"route_id": str, "trip_id": str, "stop_id": str}


@dataclass(frozen=True)
class VehiclesInServicePoint:
    time_of_day: str  # "HH:MM"
    vehicle_count: int


@dataclass(frozen=True)
class TripsByDate:
    date: str  # ISO date
    trip_count: int


@dataclass(frozen=True)
class AccuracyBucket:
    label: str
    prediction_count: int
    accurate_count: int
    accuracy_percent: float | None  # None if prediction_count == 0


@dataclass(frozen=True)
class TidesBenchmarks:
    trips_performed: int
    realtime_completeness_percent: float | None
    realtime_completeness_note: str | None
    eta_accuracy_percent: float | None
    eta_accuracy_note: str | None
    eta_accuracy_buckets: list[AccuracyBucket]


@dataclass(frozen=True)
class DashboardData:
    agency: str
    feed_start_date: date
    feed_end_date: date
    route_count: int
    trip_count: int
    stop_count: int
    busiest_date: date
    peak_vehicles: int
    peak_time: str
    vehicles_time_series: list[VehiclesInServicePoint]
    trips_by_date: list[TripsByDate]
    tides: TidesBenchmarks | None


def _read_typed_csvs(tides_files: list[Path], required_columns: set[str]) -> pd.DataFrame:
    """Concatenate every fetched CSV whose columns are a superset of `required_columns`.

    Duck-typed by column presence, like every TIDES read in this project
    (a fetched TIDES directory may hold several distinct CSV shapes side
    by side) — see
    specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files.
    """
    frames = []
    for path in tides_files:
        if path.suffix.lower() != ".csv":
            continue
        df = pd.read_csv(path, dtype=_ID_DTYPES)
        if required_columns.issubset(df.columns):
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=sorted(required_columns))
    df = pd.concat(frames, ignore_index=True)
    df["service_date"] = pd.to_datetime(df["service_date"]).dt.date
    return df


def _read_trip_stop_outcomes(tides_files: list[Path]) -> pd.DataFrame:
    return _read_typed_csvs(tides_files, _TRIP_STOP_OUTCOME_COLUMNS)


def _read_predictions(tides_files: list[Path]) -> pd.DataFrame:
    return _read_typed_csvs(tides_files, _PREDICTIONS_COLUMNS)


def _scheduled_trip_stops(feed: gk.Feed, start: date, end: date) -> pd.DataFrame:
    """(date, trip_id, stop_id) rows for every trip actually scheduled on each date in [start, end].

    The GTFS-derived denominator for ETA completeness — deliberately
    independent of TIDES, so a trip-stop TIDES never reported at all is
    still counted (and correctly comes out incomplete).
    """
    stop_times = feed.stop_times[["trip_id", "stop_id"]].drop_duplicates()
    rows = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        day_trips = feed.get_trips(date=day.strftime("%Y%m%d"))
        if day_trips.empty:
            continue
        day_stops = stop_times[stop_times["trip_id"].isin(set(day_trips["trip_id"]))].copy()
        day_stops.insert(0, "date", day)
        rows.append(day_stops)
    if not rows:
        return pd.DataFrame(columns=["date", "trip_id", "stop_id"])
    return pd.concat(rows, ignore_index=True)


def _qualifying_prediction_keys(outcomes: pd.DataFrame, predictions: pd.DataFrame) -> set[tuple]:
    """(service_date, trip_id, stop_id) keys with >=1 prediction 0-15 min before actual arrival."""
    if predictions.empty or outcomes.empty:
        return set()
    actuals = outcomes[["service_date", "trip_id", "stop_id", "actual_arrival"]].dropna(subset=["actual_arrival"])
    if actuals.empty:
        return set()
    merged = predictions.merge(actuals, on=["service_date", "trip_id", "stop_id"], how="inner")
    time_to_actual = pd.to_datetime(merged["actual_arrival"]) - pd.to_datetime(merged["sampled_at"])
    low, high = _COMPLETENESS_PREDICTION_WINDOW
    qualifying = merged[(time_to_actual >= low) & (time_to_actual < high)]
    return set(zip(qualifying["service_date"], qualifying["trip_id"], qualifying["stop_id"]))


def _eta_completeness_percent(
    feed: gk.Feed, start: date, end: date, outcomes: pd.DataFrame, predictions: pd.DataFrame
) -> tuple[float | None, str | None]:
    """ETA Completeness Benchmark: https://github.com/SwiftlyInc/ETA-Completeness-Benchmark

    See specs/data-model.md#eta-completeness for how this maps onto this
    project's GTFS + TIDES inputs.
    """
    scheduled = _scheduled_trip_stops(feed, start, end)
    denominator = len(scheduled)
    if denominator == 0:
        return None, "no scheduled trip-stops in the configured date range"
    if outcomes.empty:
        return None, "no fetched TIDES file has a trip_stop_outcomes shape"

    in_range = outcomes[(outcomes["service_date"] >= start) & (outcomes["service_date"] <= end)]
    qualifying = _qualifying_prediction_keys(in_range, predictions)

    keys = list(zip(in_range["service_date"], in_range["trip_id"], in_range["stop_id"]))
    has_qualifying_prediction = pd.Series([k in qualifying for k in keys], index=in_range.index)
    scheduled_keys = set(zip(scheduled["date"], scheduled["trip_id"], scheduled["stop_id"]))
    in_scheduled = pd.Series([k in scheduled_keys for k in keys], index=in_range.index)

    vehicle_assigned = in_range["vehicle_assigned"].astype(bool)
    trip_cancelled = in_range["trip_cancelled"].astype(bool)
    stop_skipped = in_range["stop_skipped"].astype(bool)
    complete = (vehicle_assigned & has_qualifying_prediction) | trip_cancelled | stop_skipped

    numerator = int((complete & in_scheduled).sum())
    return 100 * numerator / denominator, None


def _eta_accuracy(
    outcomes: pd.DataFrame, predictions: pd.DataFrame, start: date, end: date
) -> tuple[float | None, str | None, list[AccuracyBucket]]:
    """ETA Accuracy Benchmark: https://github.com/TransitApp/ETA-Accuracy-Benchmark

    See specs/data-model.md#eta-accuracy for how this maps onto this
    project's GTFS + TIDES inputs.
    """
    if predictions.empty:
        return None, "no fetched TIDES file has a predictions shape", []
    if outcomes.empty:
        return None, "no fetched TIDES file has a trip_stop_outcomes shape (needed for actual_arrival)", []

    predictions_in_range = predictions[(predictions["service_date"] >= start) & (predictions["service_date"] <= end)]
    if predictions_in_range.empty:
        return None, "no predictions in the configured date range", []

    actuals = outcomes[["service_date", "trip_id", "stop_id", "actual_arrival"]].dropna(subset=["actual_arrival"])
    merged = predictions_in_range.merge(actuals, on=["service_date", "trip_id", "stop_id"], how="inner")
    if merged.empty:
        return None, "no predictions have a matching actual_arrival", []

    sampled_at = pd.to_datetime(merged["sampled_at"])
    actual_arrival = pd.to_datetime(merged["actual_arrival"])
    predicted_arrival = pd.to_datetime(merged["predicted_arrival"])
    time_to_actual = actual_arrival - sampled_at
    variance = actual_arrival - predicted_arrival

    buckets = []
    bucket_accuracies = []
    for label, low_min, high_min, early_tolerance, late_tolerance in _ACCURACY_BUCKETS:
        in_bucket = (time_to_actual >= timedelta(minutes=low_min)) & (time_to_actual < timedelta(minutes=high_min))
        bucket_variance = variance[in_bucket]
        count = len(bucket_variance)
        if count == 0:
            buckets.append(AccuracyBucket(label=label, prediction_count=0, accurate_count=0, accuracy_percent=None))
            continue
        accurate = int(((bucket_variance >= -early_tolerance) & (bucket_variance <= late_tolerance)).sum())
        accuracy_percent = 100 * accurate / count
        buckets.append(
            AccuracyBucket(label=label, prediction_count=count, accurate_count=accurate, accuracy_percent=accuracy_percent)
        )
        bucket_accuracies.append(accuracy_percent)

    if not bucket_accuracies:
        return None, "no predictions fell within any of the four accuracy time buckets", buckets
    return sum(bucket_accuracies) / len(bucket_accuracies), None, buckets


def _build_tides_benchmarks(feed: gk.Feed, tides_files: list[Path], start: date, end: date) -> TidesBenchmarks:
    performed = otp.read_tides_performed(tides_files)
    scheduled_dt = pd.to_datetime(performed["scheduled_departure"])
    in_range = (scheduled_dt.dt.date >= start) & (scheduled_dt.dt.date <= end)
    performed = performed[in_range]
    performed = performed[~performed["cancelled"].astype(bool)]
    trips_performed = len(performed)

    outcomes = _read_trip_stop_outcomes(tides_files)
    predictions = _read_predictions(tides_files)

    completeness_percent, completeness_note = _eta_completeness_percent(feed, start, end, outcomes, predictions)
    accuracy_percent, accuracy_note, accuracy_buckets = _eta_accuracy(outcomes, predictions, start, end)

    return TidesBenchmarks(
        trips_performed=trips_performed,
        realtime_completeness_percent=completeness_percent,
        realtime_completeness_note=completeness_note,
        eta_accuracy_percent=accuracy_percent,
        eta_accuracy_note=accuracy_note,
        eta_accuracy_buckets=accuracy_buckets,
    )


def build_dashboard_data(
    feed: gk.Feed,
    agency: str,
    *,
    tides_files: list[Path] | None = None,
    date_range: tuple[date, date] | None = None,
) -> DashboardData:
    """Build the dashboard's data, independent of how it's rendered.

    Schedule section is always computed (GTFS-only). The TIDES section is
    computed only when both `tides_files` and `date_range` are given —
    otherwise `data.tides` is None, per
    specs/data-model.md#static-html-dashboard-report-output.
    """
    feed_start, feed_end = schedule_stats.feed_date_range(feed)
    week_days = schedule_stats.representative_week(feed)
    week_day_strs = [d.strftime("%Y%m%d") for d in week_days]

    trip_stats = feed.compute_trip_stats()

    busiest_day_str = feed.compute_busiest_date(week_day_strs)
    busiest_date = datetime.strptime(busiest_day_str, "%Y%m%d").date()

    time_series = feed.compute_network_time_series([busiest_day_str], trip_stats=trip_stats, freq="15Min")
    vehicles_time_series = [
        VehiclesInServicePoint(time_of_day=row.datetime.strftime("%H:%M"), vehicle_count=int(row.num_trips))
        for row in time_series.itertuples()
    ]

    # peak_num_trips/peak_start_time come from compute_network_stats's own
    # exact calculation (trip start/end times), not derived by taking the
    # max of the 15-minute-binned time series above, which could
    # under-report a peak that falls inside a single bin boundary.
    busy_day_stats = feed.compute_network_stats([busiest_day_str], trip_stats=trip_stats)
    peak_row = busy_day_stats.iloc[0]
    peak_vehicles = int(peak_row["peak_num_trips"])
    peak_time = str(peak_row["peak_start_time"])[:5]  # HH:MM

    daily_stats = feed.compute_network_stats(feed.get_dates(), trip_stats=trip_stats)
    trips_by_date = [
        TripsByDate(
            date=datetime.strptime(row.date, "%Y%m%d").date().isoformat(),
            trip_count=int(row.num_trips),
        )
        for row in daily_stats.itertuples()
    ]

    route_count = 0 if feed.routes is None else len(feed.routes)
    trip_count = 0 if feed.trips is None else len(feed.trips)
    stop_count = 0 if feed.stops is None else len(feed.stops)

    tides_benchmarks = None
    if tides_files and date_range:
        tides_benchmarks = _build_tides_benchmarks(feed, tides_files, date_range[0], date_range[1])

    return DashboardData(
        agency=agency,
        feed_start_date=feed_start,
        feed_end_date=feed_end,
        route_count=route_count,
        trip_count=trip_count,
        stop_count=stop_count,
        busiest_date=busiest_date,
        peak_vehicles=peak_vehicles,
        peak_time=peak_time,
        vehicles_time_series=vehicles_time_series,
        trips_by_date=trips_by_date,
        tides=tides_benchmarks,
    )


def _nice_ticks(max_value: int, target_count: int = 5) -> list[int]:
    """Evenly-spaced, round-number y-axis ticks from 0 up past max_value.

    All chart data here is non-negative trip/vehicle counts, so ticks are
    always whole numbers — avoids the classic duplicate-label bug where
    rounding fractional ticks (e.g. 0, 0.29, 0.575, 0.8625, 1.15) collapses
    several distinct ticks to the same displayed integer.
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


def _thin_indices(n: int, max_ticks: int = 8) -> list[int]:
    """Evenly-spaced indices (always including the first and last) for x-axis labels."""
    if n <= max_ticks:
        return list(range(n))
    step = (n - 1) / (max_ticks - 1)
    return sorted({round(i * step) for i in range(max_ticks)})


def _area_chart_svg(
    *, chart_id: str, points: list[tuple[str, int]], value_suffix: str = ""
) -> str:
    """A single-series area+line chart. points: list of (x_label, y_value)."""
    width, height = 720, 220
    pad_left, pad_right, pad_top, pad_bottom = 44, 12, 16, 28
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    values = [v for _, v in points]
    max_value = max(values) if values else 0
    ticks = _nice_ticks(max_value)
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

    tick_indices = _thin_indices(n)
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


def _stat_tile(label: str, value: str, note: str | None = None) -> str:
    note_html = f'<div class="stat-note">{escape(note)}</div>' if note else ""
    return f"""
<div class="stat-tile">
  <div class="stat-label">{escape(label)}</div>
  <div class="stat-value">{escape(value)}</div>
  {note_html}
</div>
""".strip()


def _data_table(headers: list[str], rows: list[tuple]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"""
<details class="data-table">
  <summary>Show data table</summary>
  <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
</details>
""".strip()


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def render_html(data: DashboardData) -> str:
    """Render the dashboard as a single self-contained HTML document (string)."""
    vehicles_points = [(p.time_of_day, p.vehicle_count) for p in data.vehicles_time_series]
    trips_points = [(t.date, t.trip_count) for t in data.trips_by_date]

    vehicles_chart = _area_chart_svg(chart_id="vehicles-chart", points=vehicles_points)
    trips_chart = _area_chart_svg(chart_id="trips-chart", points=trips_points, value_suffix=" trips")

    vehicles_table = _data_table(["Time of day", "Vehicles in service"], vehicles_points)
    trips_table = _data_table(["Date", "Scheduled trips"], trips_points)

    stat_tiles = [
        _stat_tile("Routes", str(data.route_count)),
        _stat_tile("Trips (whole feed)", str(data.trip_count)),
        _stat_tile("Stops", str(data.stop_count)),
        _stat_tile(
            "Peak vehicles in service",
            str(data.peak_vehicles),
            f"at {data.peak_time} on {data.busiest_date.isoformat()}",
        ),
    ]

    if data.tides is not None:
        stat_tiles.extend(
            [
                _stat_tile("Trips performed", str(data.tides.trips_performed)),
                _stat_tile(
                    "ETA completeness",
                    _percent(data.tides.realtime_completeness_percent),
                    data.tides.realtime_completeness_note,
                ),
                _stat_tile(
                    "ETA accuracy",
                    _percent(data.tides.eta_accuracy_percent),
                    data.tides.eta_accuracy_note,
                ),
            ]
        )
        bucket_rows = [
            (b.label, b.prediction_count, _percent(b.accuracy_percent)) for b in data.tides.eta_accuracy_buckets
        ]
        bucket_table = _data_table(["Time bucket", "Predictions", "Accuracy"], bucket_rows)
        tides_section = f"""
<section class="section">
  <h2>TIDES benchmarks</h2>
  <p class="section-note">
    Trips performed, plus the
    <a href="https://github.com/SwiftlyInc/ETA-Completeness-Benchmark">ETA Completeness Benchmark</a>
    and
    <a href="https://github.com/TransitApp/ETA-Accuracy-Benchmark">ETA Accuracy Benchmark</a>
    scores over the configured date_range. Both rest on an
    <strong>unverified assumption</strong> about the TIDES CSV shape —
    see specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files.
  </p>
  <h3 class="subsection-title">ETA accuracy by time bucket</h3>
  {bucket_table}
</section>
""".strip()
    else:
        tides_section = """
<section class="section">
  <h2>TIDES benchmarks</h2>
  <p class="section-note">
    Not shown: this agency has no tides: + date_range: configured (or
    TIDES has not been fetched yet). See
    specs/data-model.md#static-html-dashboard-report-output.
  </p>
</section>
""".strip()

    agency_escaped = escape(data.agency)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{agency_escaped} — schedule &amp; TIDES dashboard</title>
<style>
  :root {{
    color-scheme: light;
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --gridline: #e1e0d9;
    --baseline: #c3c2b7;
    --series-1: {_SERIES_COLOR_LIGHT};
    --series-1-fill: rgba(42, 120, 214, 0.10);
    --border: rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      color-scheme: dark;
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --gridline: #2c2c2a;
      --baseline: #383835;
      --series-1: {_SERIES_COLOR_DARK};
      --series-1-fill: rgba(57, 135, 229, 0.14);
      --border: rgba(255,255,255,0.10);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  main {{ max-width: 880px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); margin: 0 0 24px; }}
  .section {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 20px;
  }}
  .section h2 {{ font-size: 1.05rem; margin: 0 0 12px; }}
  .subsection-title {{ font-size: 0.85rem; color: var(--text-secondary); margin: 16px 0 6px; font-weight: 600; }}
  .section-note {{ color: var(--text-secondary); font-size: 0.9rem; }}
  .stat-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }}
  .stat-tile {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 16px;
    min-width: 150px;
    flex: 1 1 150px;
  }}
  .stat-label {{ color: var(--text-secondary); font-size: 0.82rem; }}
  .stat-value {{ font-size: 1.5rem; font-weight: 600; margin-top: 2px; }}
  .stat-note {{ color: var(--text-muted); font-size: 0.78rem; margin-top: 2px; }}
  .chart {{ width: 100%; height: auto; overflow: visible; }}
  .chart .gridline {{ stroke: var(--gridline); stroke-width: 1; }}
  .chart .axis-label {{ fill: var(--text-muted); font-size: 9px; }}
  .chart .area-fill {{ fill: var(--series-1-fill); stroke: none; }}
  .chart .line {{ fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
  .chart .peak-dot {{ fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; }}
  .chart .peak-label {{ fill: var(--text-primary); font-size: 10px; font-weight: 600; }}
  .chart .hit-point {{ fill: transparent; cursor: pointer; }}
  .chart .hit-point:focus, .chart .hit-point:hover {{ fill: var(--series-1); opacity: 0.35; outline: none; }}
  .chart .crosshair {{ stroke: var(--baseline); stroke-width: 1; }}
  .chart-tooltip {{
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
  }}
  .chart-wrap {{ position: relative; }}
  details.data-table {{ margin-top: 8px; }}
  details.data-table summary {{ cursor: pointer; color: var(--text-secondary); font-size: 0.85rem; }}
  details.data-table table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.85rem; }}
  details.data-table th, details.data-table td {{
    text-align: left;
    padding: 4px 8px;
    border-bottom: 1px solid var(--gridline);
  }}
  details.data-table th {{ color: var(--text-secondary); font-weight: 600; }}
</style>
</head>
<body>
<main>
  <h1>{agency_escaped}</h1>
  <p class="subtitle">
    Schedule &amp; TIDES dashboard &middot; feed valid
    {data.feed_start_date.isoformat()} to {data.feed_end_date.isoformat()}
  </p>

  <div class="stat-row">
    {''.join(stat_tiles)}
  </div>

  <section class="section">
    <h2>Vehicles in service by time of day</h2>
    <p class="section-note">
      Concurrent scheduled trips on {data.busiest_date.isoformat()} — the
      busiest date within the feed's representative week.
    </p>
    <div class="chart-wrap">
      {vehicles_chart}
      <div class="chart-tooltip" data-for="vehicles-chart"></div>
    </div>
    {vehicles_table}
  </section>

  <section class="section">
    <h2>Scheduled trips per service day</h2>
    <p class="section-note">
      Every date in [{data.feed_start_date.isoformat()}, {data.feed_end_date.isoformat()}]
      on which the feed schedules at least one trip. Dates with no service
      are omitted.
    </p>
    <div class="chart-wrap">
      {trips_chart}
      <div class="chart-tooltip" data-for="trips-chart"></div>
    </div>
    {trips_table}
  </section>

  {tides_section}
</main>
<script>
(function () {{
  document.querySelectorAll(".chart").forEach(function (svg) {{
    var tooltip = document.querySelector('.chart-tooltip[data-for="' + svg.id + '"]');
    var crosshair = svg.querySelector(".crosshair");
    var wrap = svg.closest(".chart-wrap");
    function show(point) {{
      var label = point.getAttribute("data-label");
      var value = point.getAttribute("data-value");
      if (tooltip) {{
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
      }}
      if (crosshair) {{
        crosshair.setAttribute("x1", point.getAttribute("cx"));
        crosshair.setAttribute("x2", point.getAttribute("cx"));
        crosshair.style.display = "block";
      }}
    }}
    function hide() {{
      if (tooltip) tooltip.style.display = "none";
      if (crosshair) crosshair.style.display = "none";
    }}
    svg.querySelectorAll(".hit-point").forEach(function (point) {{
      point.addEventListener("mouseenter", function () {{ show(point); }});
      point.addEventListener("focus", function () {{ show(point); }});
      point.addEventListener("mouseleave", hide);
      point.addEventListener("blur", hide);
    }});
  }});
}})();
</script>
</body>
</html>
"""


def write_html(html: str, output_dir: Path, agency: str, feed_start: date, feed_end: date) -> Path:
    """Write the dashboard to <output_dir>/reports/<agency>/dashboard-<start>-<end>.html."""
    reports_dir = output_dir / "reports" / agency
    reports_dir.mkdir(parents=True, exist_ok=True)
    dest = reports_dir / f"dashboard-{feed_start.isoformat()}-{feed_end.isoformat()}.html"
    dest.write_text(html)
    return dest
